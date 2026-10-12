from datetime import date, datetime, timezone
from typing import List, Optional

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base

CUSTOMER, OFFICER, ADMIN = "CUSTOMER", "OFFICER", "ADMIN"
OPEN_APP_STATUSES = ("SUBMITTED", "NEED_INFO")


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(160))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    profile: Mapped[Optional["CustomerProfile"]] = relationship(back_populates="user", uselist=False)
    accounts: Mapped[List["BankAccount"]] = relationship(back_populates="user")


class CustomerProfile(Base):
    __tablename__ = "customer_profiles"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)
    dob: Mapped[date] = mapped_column(Date)
    pan: Mapped[str] = mapped_column(String(10))
    monthly_income: Mapped[float] = mapped_column(Float)
    existing_emi: Mapped[float] = mapped_column(Float, default=0)
    credit_score: Mapped[int] = mapped_column(Integer)  # simulated bureau score
    employment_type: Mapped[str] = mapped_column(String(20))
    kyc_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    phone: Mapped[str] = mapped_column(String(15), default="")
    address: Mapped[str] = mapped_column(String(250), default="")
    city: Mapped[str] = mapped_column(String(60), default="")
    pincode: Mapped[str] = mapped_column(String(6), default="")
    employer: Mapped[str] = mapped_column(String(120), default="")
    user: Mapped["User"] = relationship(back_populates="profile")


class BankAccount(Base):
    __tablename__ = "bank_accounts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    account_no: Mapped[str] = mapped_column(String(20), unique=True)
    balance: Mapped[float] = mapped_column(Float, default=0)
    netbanking_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    is_frozen: Mapped[bool] = mapped_column(Boolean, default=False)
    daily_debit_limit: Mapped[float] = mapped_column(Float, default=500000)
    user: Mapped["User"] = relationship(back_populates="accounts")


class LoanProduct(Base):
    __tablename__ = "loan_products"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True)  # HOME / PERSONAL / AUTO / EDUCATION / GOLD
    name: Mapped[str] = mapped_column(String(80))
    min_amount: Mapped[float] = mapped_column(Float)
    max_amount: Mapped[float] = mapped_column(Float)
    min_tenure: Mapped[int] = mapped_column(Integer)
    max_tenure: Mapped[int] = mapped_column(Integer)
    base_rate: Mapped[float] = mapped_column(Float)
    min_income: Mapped[float] = mapped_column(Float)
    min_credit_score: Mapped[int] = mapped_column(Integer)
    max_foir: Mapped[float] = mapped_column(Float)
    max_ltv: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    max_age_at_maturity: Mapped[int] = mapped_column(Integer, default=65)
    required_docs: Mapped[str] = mapped_column(String(300))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class LoanApplication(Base):
    __tablename__ = "loan_applications"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("loan_products.id"))
    amount: Mapped[float] = mapped_column(Float)
    tenure_months: Mapped[int] = mapped_column(Integer)
    purpose: Mapped[str] = mapped_column(String(200), default="")
    asset_value: Mapped[float] = mapped_column(Float, default=0)
    docs: Mapped[str] = mapped_column(String(300), default="")
    status: Mapped[str] = mapped_column(String(20), default="SUBMITTED", index=True)
    rate: Mapped[float] = mapped_column(Float, default=0)
    emi: Mapped[float] = mapped_column(Float, default=0)
    foir: Mapped[float] = mapped_column(Float, default=0)
    system_score: Mapped[int] = mapped_column(Integer, default=0)
    system_recommendation: Mapped[str] = mapped_column(String(20), default="REVIEW")
    checks_json: Mapped[str] = mapped_column(Text, default="[]")
    ai_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    officer_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    officer_note: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    product: Mapped["LoanProduct"] = relationship()
    user: Mapped["User"] = relationship(foreign_keys=[user_id])


class Loan(Base):
    __tablename__ = "loans"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("loan_applications.id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("loan_products.id"))
    account_id: Mapped[int] = mapped_column(ForeignKey("bank_accounts.id"))
    principal: Mapped[float] = mapped_column(Float)
    rate: Mapped[float] = mapped_column(Float)
    tenure_months: Mapped[int] = mapped_column(Integer)
    emi: Mapped[float] = mapped_column(Float)
    outstanding: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE")  # ACTIVE / CLOSED
    disbursed_on: Mapped[date] = mapped_column(Date)
    autopay_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    mandate_status: Mapped[str] = mapped_column(String(20), default="NONE")  # NONE / ACTIVE
    mandate_limit: Mapped[float] = mapped_column(Float, default=0)
    product: Mapped["LoanProduct"] = relationship()
    account: Mapped["BankAccount"] = relationship()
    user: Mapped["User"] = relationship()
    installments: Mapped[List["Installment"]] = relationship(
        back_populates="loan", order_by="Installment.number"
    )


class Installment(Base):
    __tablename__ = "installments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    loan_id: Mapped[int] = mapped_column(ForeignKey("loans.id"), index=True)
    number: Mapped[int] = mapped_column(Integer)
    due_date: Mapped[date] = mapped_column(Date, index=True)
    emi_amount: Mapped[float] = mapped_column(Float)
    principal_part: Mapped[float] = mapped_column(Float)
    interest_part: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(20), default="PENDING")  # PENDING/PAID/FAILED/OVERDUE
    paid_on: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_failure_code: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    last_notified_on: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    loan: Mapped["Loan"] = relationship(back_populates="installments")


class Payment(Base):
    __tablename__ = "payments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    loan_id: Mapped[int] = mapped_column(ForeignKey("loans.id"), index=True)
    installment_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    amount: Mapped[float] = mapped_column(Float)
    mode: Mapped[str] = mapped_column(String(20))  # AUTOPAY / MANUAL / DISBURSAL
    status: Mapped[str] = mapped_column(String(20))
    failure_code: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Document(Base):
    """Customer document locker. One row per uploaded file; reused across applications."""
    __tablename__ = "documents"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    doc_type: Mapped[str] = mapped_column(String(30), index=True)
    filename: Mapped[str] = mapped_column(String(200))
    stored_name: Mapped[str] = mapped_column(String(80))
    content_type: Mapped[str] = mapped_column(String(40))
    size: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), default="UPLOADED")  # UPLOADED(pending review)/VERIFIED/REJECTED
    source: Mapped[str] = mapped_column(String(20), default="UPLOAD")    # UPLOAD / SAMPLE
    checks_json: Mapped[str] = mapped_column(Text, default="[]")         # automated checks + extracted fields
    reviewer_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    review_note: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(160))
    message: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(30))
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class PasswordResetRequest(Base):
    __tablename__ = "password_reset_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), index=True
    )
    status: Mapped[str] = mapped_column(
        String(20), default="PENDING", index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow
    )
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )
    reviewed_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    action: Mapped[str] = mapped_column(String(60))
    entity: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    detail: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ServiceRequest(Base):
    """Customer support/service request managed by an authorized bank officer."""
    __tablename__ = "service_requests"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    loan_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    category: Mapped[str] = mapped_column(String(30))
    subject: Mapped[str] = mapped_column(String(120))
    message: Mapped[str] = mapped_column(String(1000))
    status: Mapped[str] = mapped_column(String(20), default="OPEN", index=True)
    response: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    handled_by: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    user: Mapped["User"] = relationship()
