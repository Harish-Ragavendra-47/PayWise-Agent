"""Payment history and webhook processing service for PayWise Agent."""
from datetime import datetime
from decimal import Decimal
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session

from backend.models import Payment, Invoice, WebhookEvent
from backend.schemas import PaymentOut
from backend.services.paypal_service import paypal_service


def get_all_payments(db: Session) -> List[Dict[str, Any]]:
    """Retrieve all recorded payments with linked invoice numbers."""
    payments = db.query(Payment).order_by(Payment.paid_at.desc()).all()
    results = []
    for p in payments:
        inv = db.query(Invoice).filter(Invoice.id == p.invoice_id).first()
        results.append({
            "id": p.id,
            "invoice_id": p.invoice_id,
            "invoice_number": inv.invoice_number if inv else "N/A",
            "client_name": inv.client.name if (inv and inv.client) else "N/A",
            "paypal_transaction_id": p.paypal_transaction_id or "N/A",
            "amount": p.amount,
            "currency": p.currency,
            "status": p.status,
            "paid_at": p.paid_at
        })
    return results


def process_paypal_webhook(
    db: Session,
    headers: Dict[str, str],
    payload: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Process verified incoming PayPal Webhook event idempotently.
    Enforces Rule: Deduplication via WebhookEvents table.
    """
    event_id = payload.get("id")
    event_type = payload.get("event_type", "UNKNOWN")

    if not event_id:
        return {"status": "ignored", "reason": "Missing event ID"}

    # 1. Idempotency Check: Prevent duplicate webhook processing
    existing_event = db.query(WebhookEvent).filter(WebhookEvent.paypal_event_id == event_id).first()
    if existing_event:
        return {
            "status": "already_processed",
            "event_id": event_id,
            "processed_at": existing_event.processed_at.isoformat()
        }

    # 2. Signature verification if webhook headers are provided
    if "paypal-transmission-sig" in [k.lower() for k in headers.keys()]:
        is_verified = paypal_service.verify_webhook_signature(headers, payload)
        if not is_verified:
            return {"status": "rejected", "reason": "Webhook signature verification failed"}

    # 3. Process event resource
    resource = payload.get("resource", {})

    if event_type == "INVOICING.INVOICE.PAID":
        invoice_obj = resource.get("invoice", resource)
        paypal_inv_id = invoice_obj.get("id")
        if paypal_inv_id:
            inv = db.query(Invoice).filter(Invoice.paypal_invoice_id == paypal_inv_id).first()
            if inv:
                inv.status = "PAID"
                # Record payment
                amount_val = Decimal("0.00")
                payments_list = invoice_obj.get("payments", {}).get("transactions", [])
                tx_id = f"WH-TX-{event_id[:16]}"
                if payments_list:
                    tx_id = payments_list[0].get("payment_id", tx_id)
                    amt = payments_list[0].get("amount", {}).get("value")
                    if amt:
                        amount_val = Decimal(str(amt))
                if amount_val <= Decimal("0"):
                    amount_val = inv.total_amount

                new_pmt = Payment(
                    invoice_id=inv.id,
                    paypal_transaction_id=tx_id,
                    amount=amount_val,
                    currency=inv.currency,
                    status="COMPLETED",
                    paid_at=datetime.utcnow()
                )
                db.add(new_pmt)

    elif event_type == "INVOICING.INVOICE.CANCELLED":
        invoice_obj = resource.get("invoice", resource)
        paypal_inv_id = invoice_obj.get("id")
        if paypal_inv_id:
            inv = db.query(Invoice).filter(Invoice.paypal_invoice_id == paypal_inv_id).first()
            if inv and inv.status != "PAID":
                inv.status = "CANCELLED"

    elif event_type == "INVOICING.INVOICE.REFUNDED":
        invoice_obj = resource.get("invoice", resource)
        paypal_inv_id = invoice_obj.get("id")
        if paypal_inv_id:
            inv = db.query(Invoice).filter(Invoice.paypal_invoice_id == paypal_inv_id).first()
            if inv:
                inv.status = "REFUNDED"

    # 4. Save event for deduplication
    webhook_log = WebhookEvent(
        paypal_event_id=event_id,
        event_type=event_type,
        processed_at=datetime.utcnow()
    )
    db.add(webhook_log)
    db.commit()

    return {
        "status": "success",
        "event_id": event_id,
        "event_type": event_type,
        "processed": True
    }
