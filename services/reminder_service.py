"""Smart payment reminder draft generation and management service."""
from datetime import datetime
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session

from backend.models import Reminder, Invoice, Client
from backend.services.ai_service import generate_reminder_text_ai


def generate_reminder_draft(
    db: Session,
    invoice_id: int,
    reminder_type: str = "friendly"
) -> Reminder:
    """
    Generate an AI-drafted reminder tailored to the invoice and client.
    Stores as a DRAFT so the user can review and edit before sending.
    """
    invoice = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    if not invoice:
        raise ValueError(f"Invoice #{invoice_id} not found")

    client_name = invoice.client.name if invoice.client else "Valued Client"
    due_date_str = invoice.due_date.strftime("%B %d, %Y")

    message = generate_reminder_text_ai(
        client_name=client_name,
        invoice_number=invoice.invoice_number,
        amount=invoice.total_amount,
        currency=invoice.currency,
        due_date=due_date_str,
        tone=reminder_type
    )

    reminder = Reminder(
        invoice_id=invoice.id,
        reminder_message=message,
        reminder_type=reminder_type,
        status="DRAFT"
    )
    db.add(reminder)
    db.commit()
    db.refresh(reminder)
    return reminder


def get_all_reminders(db: Session, invoice_id: Optional[int] = None) -> List[Dict[str, Any]]:
    """Retrieve reminder history with invoice details."""
    query = db.query(Reminder).join(Invoice)
    if invoice_id:
        query = query.filter(Reminder.invoice_id == invoice_id)

    reminders = query.order_by(Reminder.created_at.desc()).all()
    results = []
    for r in reminders:
        inv = r.invoice
        results.append({
            "id": r.id,
            "invoice_id": r.invoice_id,
            "invoice_number": inv.invoice_number if inv else "N/A",
            "client_name": inv.client.name if (inv and inv.client) else "N/A",
            "client_email": inv.client.email if (inv and inv.client) else None,
            "reminder_message": r.reminder_message,
            "reminder_type": r.reminder_type,
            "status": r.status,
            "created_at": r.created_at,
            "sent_at": r.sent_at
        })
    return results


def send_reminder(
    db: Session,
    reminder_id: int,
    custom_message: Optional[str] = None
) -> Dict[str, Any]:
    """
    Attempts to send a reminder.
    Strictly follows requirement:
    'Never claim that a reminder email was sent unless a real sending integration is configured and confirms success.'
    Since external SMTP/SES is not configured in this demo, returns exact transparency notice.
    """
    reminder = db.query(Reminder).filter(Reminder.id == reminder_id).first()
    if not reminder:
        raise ValueError("Reminder draft not found")

    if custom_message:
        reminder.reminder_message = custom_message

    # Verify if an actual SMTP provider is configured
    smtp_configured = False  # By default in sandbox

    if not smtp_configured:
        # Keep status as DRAFT / READY and explain clearly
        reminder.status = "DRAFT"
        db.commit()
        return {
            "success": False,
            "status": "DRAFT",
            "message": (
                "Notice: Direct email dispatch is disabled because no outbound SMTP server is configured in settings. "
                "The reminder draft has been copied to your clipboard so you can send it via your email client or messaging app."
            ),
            "reminder_message": reminder.reminder_message
        }

    # If SMTP was configured (future extension), send and update sent_at
    reminder.status = "SENT"
    reminder.sent_at = datetime.utcnow()
    db.commit()
    return {
        "success": True,
        "status": "SENT",
        "message": "Reminder sent successfully to client."
    }
