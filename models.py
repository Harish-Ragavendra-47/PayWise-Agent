"""SQLAlchemy database models for PayWise Agent."""
from datetime import datetime
from decimal import Decimal
from sqlalchemy import (
    Column,
    Integer,
    String,
    DateTime,
    Date,
    Numeric,
    ForeignKey,
    Text,
)
from sqlalchemy.orm import relationship
from backend.database import Base


class Client(Base):
    """Client model representing an invoice recipient or customer."""
    __tablename__ = "clients"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False, index=True)
    email = Column(String(255), nullable=True, index=True)
    phone = Column(String(50), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    invoices = relationship("Invoice", back_populates="client", cascade="all, delete-orphan")


class Invoice(Base):
    """Invoice model for tracking billing requests, amounts, and PayPal sync."""
    __tablename__ = "invoices"

    id = Column(Integer, primary_key=True, index=True)
    invoice_number = Column(String(64), unique=True, index=True, nullable=False)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False)
    description = Column(Text, nullable=False)
    quantity = Column(Numeric(10, 2, asdecimal=True), nullable=False, default=Decimal("1.00"))
    unit_price = Column(Numeric(12, 2, asdecimal=True), nullable=False)
    total_amount = Column(Numeric(12, 2, asdecimal=True), nullable=False)
    currency = Column(String(3), nullable=False, default="USD")
    issue_date = Column(Date, nullable=False)
    due_date = Column(Date, nullable=False)
    # Statuses: DRAFT, SENT, PAID, OVERDUE, CANCELLED
    status = Column(String(32), nullable=False, default="DRAFT", index=True)
    paypal_invoice_id = Column(String(128), nullable=True, index=True)
    paypal_invoice_url = Column(String(512), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    client = relationship("Client", back_populates="invoices")
    payments = relationship("Payment", back_populates="invoice", cascade="all, delete-orphan")
    reminders = relationship("Reminder", back_populates="invoice", cascade="all, delete-orphan")


class Payment(Base):
    """Payment record linked to an invoice."""
    __tablename__ = "payments"

    id = Column(Integer, primary_key=True, index=True)
    invoice_id = Column(Integer, ForeignKey("invoices.id"), nullable=False)
    paypal_transaction_id = Column(String(128), nullable=True, index=True)
    amount = Column(Numeric(12, 2, asdecimal=True), nullable=False)
    currency = Column(String(3), nullable=False)
    # Statuses: COMPLETED, PENDING, REFUNDED, FAILED
    status = Column(String(32), nullable=False, default="COMPLETED")
    paid_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    invoice = relationship("Invoice", back_populates="payments")


class Reminder(Base):
    """Smart payment reminder draft and sending record."""
    __tablename__ = "reminders"

    id = Column(Integer, primary_key=True, index=True)
    invoice_id = Column(Integer, ForeignKey("invoices.id"), nullable=False)
    reminder_message = Column(Text, nullable=False)
    # Reminder tone: friendly, professional, urgent
    reminder_type = Column(String(32), nullable=False, default="professional")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    sent_at = Column(DateTime, nullable=True)
    # Status: DRAFT, SENT, FAILED
    status = Column(String(32), nullable=False, default="DRAFT")

    invoice = relationship("Invoice", back_populates="reminders")


class WebhookEvent(Base):
    """PayPal webhook deduplication and event log."""
    __tablename__ = "webhook_events"

    id = Column(Integer, primary_key=True, index=True)
    paypal_event_id = Column(String(128), unique=True, index=True, nullable=False)
    event_type = Column(String(128), nullable=False)
    processed_at = Column(DateTime, default=datetime.utcnow, nullable=False)
