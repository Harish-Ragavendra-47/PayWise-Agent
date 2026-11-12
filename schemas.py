"""Pydantic schemas for request and response validation in PayWise Agent."""
from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, ConfigDict, field_validator


# ==========================================
# Client Schemas
# ==========================================
class ClientBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255, description="Client or company name")
    email: Optional[str] = Field(None, max_length=255, description="Client email address")
    phone: Optional[str] = Field(None, max_length=50, description="Client phone number")


class ClientCreate(ClientBase):
    pass


class ClientOut(ClientBase):
    id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ==========================================
# Invoice Schemas
# ==========================================
class InvoiceItemPreview(BaseModel):
    description: str
    quantity: Decimal = Field(default=Decimal("1.00"), ge=Decimal("0.01"))
    unit_price: Decimal = Field(..., ge=Decimal("0.00"))
    total_amount: Decimal = Field(..., ge=Decimal("0.00"))


class InvoicePreviewRequest(BaseModel):
    client_name: str
    client_email: Optional[str] = None
    client_phone: Optional[str] = None
    description: str
    quantity: Decimal = Field(default=Decimal("1.00"), ge=Decimal("0.01"))
    unit_price: Decimal = Field(..., ge=Decimal("0.00"))
    currency: str = Field(default="USD", min_length=3, max_length=3)
    issue_date: Optional[date] = None
    due_date: Optional[date] = None


class InvoicePreviewResponse(BaseModel):
    client_name: str
    client_email: Optional[str] = None
    client_phone: Optional[str] = None
    description: str
    quantity: Decimal
    unit_price: Decimal
    total_amount: Decimal
    currency: str
    issue_date: date
    due_date: date
    missing_fields: List[str] = []
    currency_supported_by_sandbox: bool = True
    warnings: List[str] = []


class InvoiceCreate(BaseModel):
    client_name: str = Field(..., min_length=1)
    client_email: Optional[str] = None
    client_phone: Optional[str] = None
    description: str = Field(..., min_length=1)
    quantity: Decimal = Field(default=Decimal("1.00"), ge=Decimal("0.01"))
    unit_price: Decimal = Field(..., ge=Decimal("0.00"))
    currency: str = Field(default="USD", min_length=3, max_length=3)
    issue_date: Optional[date] = None
    due_date: date
    create_in_paypal: bool = Field(default=False, description="Whether to also create in PayPal Sandbox immediately")

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, v: str) -> str:
        return v.upper().strip()


class InvoiceUpdate(BaseModel):
    client_name: Optional[str] = None
    client_email: Optional[str] = None
    client_phone: Optional[str] = None
    description: Optional[str] = None
    quantity: Optional[Decimal] = None
    unit_price: Optional[Decimal] = None
    currency: Optional[str] = None
    due_date: Optional[date] = None
    status: Optional[str] = None


class InvoiceOut(BaseModel):
    id: int
    invoice_number: str
    client_id: int
    client: Optional[ClientOut] = None
    description: str
    quantity: Decimal
    unit_price: Decimal
    total_amount: Decimal
    currency: str
    issue_date: date
    due_date: date
    status: str
    paypal_invoice_id: Optional[str] = None
    paypal_invoice_url: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ==========================================
# AI Extraction Schemas
# ==========================================
class AIExtractRequest(BaseModel):
    user_prompt: str = Field(..., min_length=3, description="Natural language prompt describing the invoice to create")


class AIExtractResponse(BaseModel):
    success: bool
    client_name: Optional[str] = None
    client_email: Optional[str] = None
    description: Optional[str] = None
    quantity: Decimal = Decimal("1.00")
    unit_price: Optional[Decimal] = None
    total_amount: Optional[Decimal] = None
    currency: str = "USD"
    issue_date: Optional[date] = None
    due_date: Optional[date] = None
    missing_fields: List[str] = []
    confidence_notes: Optional[str] = None
    raw_prompt: str


# ==========================
# Payment Schemas
# ==========================
class PaymentOut(BaseModel):
    id: int
    invoice_id: int
    invoice_number: Optional[str] = None
    paypal_transaction_id: Optional[str] = None
    amount: Decimal
    currency: str
    status: str
    paid_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ==========================
# Reminder Schemas
# ==========================
class ReminderGenerateRequest(BaseModel):
    invoice_id: int
    reminder_type: str = Field(default="friendly", description="friendly, professional, or urgent")


class ReminderSendRequest(BaseModel):
    reminder_id: Optional[int] = None
    invoice_id: int
    reminder_message: str
    reminder_type: str = "friendly"
    recipient_email: Optional[str] = None


class ReminderOut(BaseModel):
    id: int
    invoice_id: int
    reminder_message: str
    reminder_type: str
    created_at: datetime
    sent_at: Optional[datetime] = None
    status: str

    model_config = ConfigDict(from_attributes=True)


# ==========================
# Dashboard Schemas
# ==========================
class DashboardSummary(BaseModel):
    total_invoices: int
    paid_invoices: int
    pending_invoices: int
    overdue_invoices: int
    total_paid_amount: Decimal
    outstanding_amount: Decimal
    currency: str
    status_counts: Dict[str, int]
    recent_invoices: List[InvoiceOut]


# ==========================
# Health / System Status
# ==========================
class HealthResponse(BaseModel):
    status: str
    version: str
    gemini_configured: bool = False
    paypal_configured: bool
    paypal_environment: str
    database_connected: bool
