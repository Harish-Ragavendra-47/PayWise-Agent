"""Business logic for invoice creation, calculations, preview, and PayPal coordination."""
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import List, Optional, Tuple, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import or_, func

from backend.models import Invoice, Client, Payment
from backend.schemas import InvoiceCreate, InvoicePreviewRequest, InvoicePreviewResponse
from backend.services.paypal_service import paypal_service, PayPalError, PayPalCredentialsMissingError
from backend.utils.security import validate_currency_support, sanitize_text
from backend.config import settings


def generate_next_invoice_number(db: Session) -> str:
    """Generate a clean sequential invoice identifier, e.g. INV-1001."""
    count = db.query(func.count(Invoice.id)).scalar() or 0
    next_num = 1001 + count
    candidate = f"INV-{next_num}"
    # Verify uniqueness
    while db.query(Invoice).filter(Invoice.invoice_number == candidate).first():
        next_num += 1
        candidate = f"INV-{next_num}"
    return candidate


def preview_invoice(request: InvoicePreviewRequest) -> InvoicePreviewResponse:
    """
    Generate an editable preview for the user before committing to database or PayPal.
    Validates amounts, dates, currency rules, and flags any missing fields.
    """
    missing_fields = []
    warnings = []

    client_name = sanitize_text(request.client_name)
    if not client_name:
        missing_fields.append("client_name")

    if not request.client_email:
        missing_fields.append("client_email")

    description = sanitize_text(request.description)
    if not description:
        missing_fields.append("description")

    quantity = Decimal(str(request.quantity or "1.00"))
    if quantity <= Decimal("0"):
        quantity = Decimal("1.00")

    unit_price = Decimal(str(request.unit_price or "0.00"))
    total_amount = (quantity * unit_price).quantize(Decimal("0.01"))

    currency = request.currency.upper().strip()
    is_curr_supported, curr_msg = validate_currency_support(currency)
    if not is_curr_supported:
        warnings.append(curr_msg)

    issue_date = request.issue_date or date.today()
    due_date = request.due_date or (issue_date + timedelta(days=7))

    if due_date < issue_date:
        warnings.append("Due date is earlier than issue date.")

    return InvoicePreviewResponse(
        client_name=client_name or "Unknown Client",
        client_email=request.client_email,
        client_phone=request.client_phone,
        description=description or "Service description",
        quantity=quantity,
        unit_price=unit_price,
        total_amount=total_amount,
        currency=currency,
        issue_date=issue_date,
        due_date=due_date,
        missing_fields=missing_fields,
        currency_supported_by_sandbox=is_curr_supported,
        warnings=warnings
    )


def create_invoice(db: Session, data: InvoiceCreate) -> Invoice:
    """
    Create a new client (or match existing) and persist an invoice.
    Optionally provisions the invoice inside PayPal Sandbox if requested.
    """
    # Currency support check
    is_supported, reason = validate_currency_support(data.currency)
    if not is_supported:
        raise ValueError(reason)

    # 1. Resolve or create client
    client_name = sanitize_text(data.client_name)
    client_email = data.client_email.strip() if data.client_email else None
    
    client = None
    if client_email:
        client = db.query(Client).filter(Client.email == client_email).first()
    if not client:
        client = db.query(Client).filter(Client.name == client_name).first()
        
    if not client:
        client = Client(
            name=client_name,
            email=client_email,
            phone=data.client_phone
        )
        db.add(client)
        db.flush()
    else:
        # Update email/phone if provided
        if client_email and not client.email:
            client.email = client_email
        if data.client_phone and not client.phone:
            client.phone = data.client_phone

    # 2. Financial calculation using Decimal
    quantity = Decimal(str(data.quantity)).quantize(Decimal("0.01"))
    unit_price = Decimal(str(data.unit_price)).quantize(Decimal("0.01"))
    total_amount = (quantity * unit_price).quantize(Decimal("0.01"))

    invoice_number = generate_next_invoice_number(db)
    issue_date = data.issue_date or date.today()
    due_date = data.due_date

    paypal_invoice_id = None
    paypal_invoice_url = None
    initial_status = "DRAFT"

    # 3. Create in PayPal Sandbox if explicitly requested
    if data.create_in_paypal:
        if not settings.is_paypal_configured:
            raise PayPalCredentialsMissingError(
                "Cannot create PayPal Sandbox invoice because PayPal credentials are missing. "
                "Save as draft locally or configure PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET."
            )
        paypal_result = paypal_service.create_invoice(
            invoice_number=invoice_number,
            client_name=client.name,
            client_email=client.email,
            description=sanitize_text(data.description),
            quantity=quantity,
            unit_price=unit_price,
            currency=data.currency,
            issue_date=issue_date.isoformat(),
            due_date=due_date.isoformat()
        )
        paypal_invoice_id = paypal_result.get("paypal_invoice_id")
        paypal_invoice_url = paypal_result.get("paypal_invoice_url")

    invoice = Invoice(
        invoice_number=invoice_number,
        client_id=client.id,
        description=sanitize_text(data.description),
        quantity=quantity,
        unit_price=unit_price,
        total_amount=total_amount,
        currency=data.currency,
        issue_date=issue_date,
        due_date=due_date,
        status=initial_status,
        paypal_invoice_id=paypal_invoice_id,
        paypal_invoice_url=paypal_invoice_url
    )

    db.add(invoice)
    db.commit()
    db.refresh(invoice)
    return invoice


def send_invoice_via_paypal(db: Session, invoice_id: int) -> Invoice:
    """
    Send an invoice to the client via PayPal Invoicing API.
    If not yet registered on PayPal Sandbox, it creates it first, then sends it.
    Updates the local record with PayPal's actual hosted payment link.
    """
    invoice = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    if not invoice:
        raise ValueError("Invoice not found")

    if not settings.is_paypal_configured:
        raise PayPalCredentialsMissingError(
            "PayPal credentials are required to send an invoice via PayPal Sandbox. "
            "Please configure your PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET."
        )

    # If not registered on PayPal yet, create it first
    if not invoice.paypal_invoice_id:
        paypal_result = paypal_service.create_invoice(
            invoice_number=invoice.invoice_number,
            client_name=invoice.client.name,
            client_email=invoice.client.email,
            description=invoice.description,
            quantity=invoice.quantity,
            unit_price=invoice.unit_price,
            currency=invoice.currency,
            issue_date=invoice.issue_date.isoformat(),
            due_date=invoice.due_date.isoformat()
        )
        invoice.paypal_invoice_id = paypal_result.get("paypal_invoice_id")
        invoice.paypal_invoice_url = paypal_result.get("paypal_invoice_url")

    # Send through PayPal
    send_result = paypal_service.send_invoice(invoice.paypal_invoice_id)
    invoice.status = "SENT"
    if send_result.get("paypal_invoice_url"):
        invoice.paypal_invoice_url = send_result.get("paypal_invoice_url")

    db.commit()
    db.refresh(invoice)
    return invoice


def sync_invoice_status(db: Session, invoice_id: int) -> Dict[str, Any]:
    """
    Synchronize invoice status against PayPal's actual records.
    Never fakes payment; records verified payments from PayPal.
    """
    invoice = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    if not invoice:
        raise ValueError("Invoice not found")

    if not invoice.paypal_invoice_id:
        # Check if overdue based on calendar date
        if invoice.status == "SENT" and invoice.due_date < date.today():
            invoice.status = "OVERDUE"
            db.commit()
            db.refresh(invoice)
        return {
            "invoice_id": invoice.id,
            "status": invoice.status,
            "synced_with_paypal": False,
            "message": "Invoice is stored locally and has not been dispatched to PayPal Sandbox."
        }

    paypal_data = paypal_service.get_invoice_details(invoice.paypal_invoice_id)
    paypal_status = paypal_data.get("status")

    if paypal_data.get("paypal_invoice_url"):
        invoice.paypal_invoice_url = paypal_data.get("paypal_invoice_url")

    # If marked paid on PayPal
    if paypal_status == "PAID":
        invoice.status = "PAID"
        # Record payment if not already recorded
        existing_payment = db.query(Payment).filter(Payment.invoice_id == invoice.id).first()
        if not existing_payment:
            total_paid = paypal_data.get("total_paid", invoice.total_amount)
            txs = paypal_data.get("transactions", [])
            tx_id = txs[0].get("payment_id") if txs else f"PP-TX-{invoice.paypal_invoice_id[:16]}"
            new_payment = Payment(
                invoice_id=invoice.id,
                paypal_transaction_id=tx_id,
                amount=total_paid if total_paid > Decimal("0") else invoice.total_amount,
                currency=invoice.currency,
                status="COMPLETED",
                paid_at=datetime.utcnow()
            )
            db.add(new_payment)

    elif paypal_status == "CANCELLED":
        invoice.status = "CANCELLED"
    elif paypal_status in ("SENT", "DRAFT"):
        if paypal_status == "SENT" and invoice.due_date < date.today():
            invoice.status = "OVERDUE"
        else:
            invoice.status = paypal_status

    db.commit()
    db.refresh(invoice)

    return {
        "invoice_id": invoice.id,
        "status": invoice.status,
        "paypal_invoice_id": invoice.paypal_invoice_id,
        "paypal_invoice_url": invoice.paypal_invoice_url,
        "synced_with_paypal": True,
        "message": f"Successfully synchronized with PayPal. Live status: {invoice.status}"
    }


def cancel_invoice(db: Session, invoice_id: int) -> Invoice:
    """Cancel invoice in database and on PayPal if registered."""
    invoice = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    if not invoice:
        raise ValueError("Invoice not found")

    if invoice.status == "PAID":
        raise ValueError("Cannot cancel an invoice that is already paid.")

    if invoice.paypal_invoice_id and settings.is_paypal_configured:
        try:
            paypal_service.cancel_invoice(invoice.paypal_invoice_id)
        except PayPalError as e:
            # If PayPal says invalid state, raise clear message
            raise ValueError(f"PayPal cancellation failed: {str(e)}")

    invoice.status = "CANCELLED"
    db.commit()
    db.refresh(invoice)
    return invoice


def get_all_invoices(
    db: Session,
    status: Optional[str] = None,
    search: Optional[str] = None
) -> List[Invoice]:
    """Retrieve invoices with optional filtering and search."""
    # Check and update overdue invoices on retrieval
    today = date.today()
    overdue_invoices = db.query(Invoice).filter(
        Invoice.status == "SENT",
        Invoice.due_date < today
    ).all()
    for inv in overdue_invoices:
        inv.status = "OVERDUE"
    if overdue_invoices:
        db.commit()

    query = db.query(Invoice).join(Client)

    if status and status.upper() != "ALL":
        query = query.filter(Invoice.status == status.upper())

    if search:
        term = f"%{search.strip()}%"
        query = query.filter(
            or_(
                Invoice.invoice_number.ilike(term),
                Invoice.description.ilike(term),
                Client.name.ilike(term),
                Client.email.ilike(term)
            )
        )

    return query.order_by(Invoice.created_at.desc()).all()
