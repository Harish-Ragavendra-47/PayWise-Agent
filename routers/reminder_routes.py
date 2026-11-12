"""Smart payment reminder API routes."""
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.schemas import ReminderGenerateRequest, ReminderOut
from backend.services.reminder_service import (
    generate_reminder_draft,
    get_all_reminders,
    send_reminder
)

router = APIRouter(prefix="/api/reminders", tags=["Smart Reminders"])


@router.post("/generate", response_model=ReminderOut)
def api_generate_reminder(request: ReminderGenerateRequest, db: Session = Depends(get_db)):
    """Generate an AI-drafted payment reminder for an invoice."""
    try:
        reminder = generate_reminder_draft(db, request.invoice_id, request.reminder_type)
        return reminder
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to generate reminder: {str(exc)}")


@router.get("", response_model=List[dict])
def api_get_reminders(
    invoice_id: Optional[int] = Query(None, description="Optional invoice ID filter"),
    db: Session = Depends(get_db)
):
    """Retrieve reminder history."""
    return get_all_reminders(db, invoice_id=invoice_id)


@router.post("/{reminder_id}/send")
def api_send_reminder(reminder_id: int, payload: dict = None, db: Session = Depends(get_db)):
    """
    Attempt to send a payment reminder to client.
    Transparently reports if SMTP outbound email is configured or if message is copied for manual sending.
    """
    custom_msg = payload.get("message") if payload else None
    try:
        return send_reminder(db, reminder_id, custom_message=custom_msg)
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(ve))
