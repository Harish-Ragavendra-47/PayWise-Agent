"""Dashboard analytics and financial summary API routes."""
from datetime import date
from decimal import Decimal
from typing import Dict
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func

from backend.database import get_db
from backend.models import Invoice, Payment
from backend.schemas import DashboardSummary, InvoiceOut

router = APIRouter(prefix="/api/dashboard", tags=["Dashboard"])


@router.get("/summary", response_model=DashboardSummary)
def api_get_dashboard_summary(db: Session = Depends(get_db)):
    """
    Retrieve live dashboard statistics computed strictly from database records.
    No hardcoded statistics.
    """
    today = date.today()

    # Update any overdue invoices first
    overdue_candidates = db.query(Invoice).filter(
        Invoice.status == "SENT",
        Invoice.due_date < today
    ).all()
    for inv in overdue_candidates:
        inv.status = "OVERDUE"
    if overdue_candidates:
        db.commit()

    all_invoices = db.query(Invoice).all()

    total_invoices = len(all_invoices)
    paid_count = 0
    pending_count = 0
    overdue_count = 0

    status_counts: Dict[str, int] = {
        "DRAFT": 0,
        "SENT": 0,
        "PAID": 0,
        "OVERDUE": 0,
        "CANCELLED": 0
    }

    outstanding_amount = Decimal("0.00")

    for inv in all_invoices:
        status_upper = inv.status.upper()
        if status_upper in status_counts:
            status_counts[status_upper] += 1
        else:
            status_counts[status_upper] = 1

        if status_upper == "PAID":
            paid_count += 1
        elif status_upper in ("DRAFT", "SENT"):
            pending_count += 1
            if status_upper == "SENT":
                outstanding_amount += inv.total_amount
        elif status_upper == "OVERDUE":
            overdue_count += 1
            outstanding_amount += inv.total_amount

    # Total paid amount computed strictly from verified payments table
    total_paid_result = db.query(func.sum(Payment.amount)).filter(Payment.status == "COMPLETED").scalar()
    total_paid_amount = Decimal(str(total_paid_result or "0.00")).quantize(Decimal("0.01"))
    outstanding_amount = outstanding_amount.quantize(Decimal("0.01"))

    # Recent 6 invoices
    recent_invoices = db.query(Invoice).order_by(Invoice.created_at.desc()).limit(6).all()

    return DashboardSummary(
        total_invoices=total_invoices,
        paid_invoices=paid_count,
        pending_invoices=pending_count,
        overdue_invoices=overdue_count,
        total_paid_amount=total_paid_amount,
        outstanding_amount=outstanding_amount,
        currency="USD",
        status_counts=status_counts,
        recent_invoices=recent_invoices
    )
