"""Payment tracking and PayPal webhook API routes."""
from typing import List, Dict, Any
from fastapi import APIRouter, Depends, Request, Header, HTTPException, status
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.services.payment_service import get_all_payments, process_paypal_webhook

router = APIRouter(tags=["Payments & Webhooks"])


@router.get("/api/payments")
def api_get_payments(db: Session = Depends(get_db)):
    """Retrieve all verified payment records."""
    return get_all_payments(db)


@router.post("/api/webhooks/paypal")
async def api_paypal_webhook(
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Handle PayPal Invoicing and Payment Webhook events.
    Verifies event authenticity and processes idempotently.
    """
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON body")

    headers = dict(request.headers)
    result = process_paypal_webhook(db, headers, payload)
    return result
