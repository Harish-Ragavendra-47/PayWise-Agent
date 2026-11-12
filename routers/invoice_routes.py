"""Invoice management API routes."""
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import Invoice
from backend.schemas import (
    InvoiceCreate,
    InvoiceOut,
    InvoicePreviewRequest,
    InvoicePreviewResponse
)
from backend.services.invoice_service import (
    preview_invoice,
    create_invoice,
    get_all_invoices,
    send_invoice_via_paypal,
    sync_invoice_status,
    cancel_invoice
)
from backend.services.paypal_service import PayPalCredentialsMissingError, PayPalError

router = APIRouter(prefix="/api/invoices", tags=["Invoices"])


@router.post("/preview", response_model=InvoicePreviewResponse)
def api_preview_invoice(request: InvoicePreviewRequest):
    """Generate an editable preview of an invoice with field validations and calculated totals."""
    return preview_invoice(request)


@router.post("", response_model=InvoiceOut, status_code=status.HTTP_201_CREATED)
def api_create_invoice(data: InvoiceCreate, db: Session = Depends(get_db)):
    """
    Create a new invoice. If create_in_paypal is True, it will attempt to provision
    the invoice inside PayPal Sandbox.
    """
    try:
        invoice = create_invoice(db, data)
        return invoice
    except PayPalCredentialsMissingError as pe:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(pe))
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))
    except PayPalError as ppe:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(ppe))
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to create invoice: {str(exc)}")


@router.get("", response_model=List[InvoiceOut])
def api_get_invoices(
    status: Optional[str] = Query(None, description="Filter by status: DRAFT, SENT, PAID, OVERDUE, CANCELLED"),
    search: Optional[str] = Query(None, description="Search term for client, number, or description"),
    db: Session = Depends(get_db)
):
    """List all invoices with optional filtering and search."""
    return get_all_invoices(db, status=status, search=search)


@router.get("/{invoice_id}", response_model=InvoiceOut)
def api_get_invoice(invoice_id: int, db: Session = Depends(get_db)):
    """Retrieve full details of a specific invoice."""
    invoice = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    if not invoice:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Invoice #{invoice_id} not found")
    return invoice


@router.post("/{invoice_id}/send", response_model=InvoiceOut)
def api_send_invoice(invoice_id: int, db: Session = Depends(get_db)):
    """
    Send an invoice to the client via PayPal Sandbox.
    Creates the invoice on PayPal if not already registered and updates local status.
    """
    try:
        invoice = send_invoice_via_paypal(db, invoice_id)
        return invoice
    except PayPalCredentialsMissingError as pe:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(pe))
    except PayPalError as ppe:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(ppe))
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))


@router.post("/{invoice_id}/sync")
def api_sync_invoice(invoice_id: int, db: Session = Depends(get_db)):
    """
    Synchronize invoice status against PayPal's verified records.
    Never fakes payment; pulls actual status from PayPal.
    """
    try:
        return sync_invoice_status(db, invoice_id)
    except PayPalCredentialsMissingError as pe:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(pe))
    except PayPalError as ppe:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(ppe))
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))


@router.post("/{invoice_id}/cancel", response_model=InvoiceOut)
def api_cancel_invoice(invoice_id: int, db: Session = Depends(get_db)):
    """Cancel an invoice in database and in PayPal Sandbox if registered."""
    try:
        invoice = cancel_invoice(db, invoice_id)
        return invoice
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))
