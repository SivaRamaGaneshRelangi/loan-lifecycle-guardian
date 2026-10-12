from datetime import date
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, field_validator

DOC_TYPES = {"ID_PROOF", "ADDRESS_PROOF", "INCOME_PROOF", "PROPERTY_PAPERS",
             "VEHICLE_QUOTATION", "ADMISSION_LETTER", "GOLD_VALUATION"}


class RegisterIn(BaseModel):
    username: str = Field(pattern=r"^[a-zA-Z0-9_]{4,30}$")
    password: str = Field(min_length=8, max_length=72)
    full_name: str = Field(min_length=2, max_length=100)
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=160)
    dob: date
    phone: str = Field(default="", pattern=r"^$|^[0-9]{10}$")
    address: str = Field(default="", max_length=250)
    city: str = Field(default="", max_length=60)
    pincode: str = Field(default="", pattern=r"^$|^[0-9]{6}$")
    pan: str = Field(pattern=r"^[A-Z]{5}[0-9]{4}[A-Z]$")
    monthly_income: float = Field(gt=0, le=10_000_000)
    existing_emi: float = Field(ge=0, default=0)
    employment_type: Literal["SALARIED", "SELF_EMPLOYED"]

    @field_validator("password")
    @classmethod
    def strong(cls, v):
        if not (any(c.isalpha() for c in v) and any(c.isdigit() for c in v)):
            raise ValueError("Password must contain letters and digits")
        return v

    @field_validator("dob")
    @classmethod
    def adult(cls, v):
        t = date.today()
        age = t.year - v.year - ((t.month, t.day) < (v.month, v.day))
        if age < 18 or age > 80:
            raise ValueError("Age must be between 18 and 80")
        return v


class LoginIn(BaseModel):
    username: str
    password: str


class StaffCreateIn(BaseModel):
    username: str = Field(pattern=r"^[a-zA-Z0-9_]{4,30}$")
    password: str = Field(min_length=8, max_length=72)
    full_name: str = Field(min_length=2, max_length=100)
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    role: Literal["OFFICER", "ADMIN"]


class ApplicationIn(BaseModel):
    product_code: str
    amount: float = Field(gt=0, le=100_000_000)
    tenure_months: int = Field(gt=0, le=480)
    purpose: str = Field(default="", max_length=200)
    asset_value: float = Field(default=0, ge=0)
    # Deprecated/ignored: documents now come from the customer's document locker (verified server-side).
    docs: List[str] = []


class DecisionIn(BaseModel):
    decision: Literal["approve", "reject", "need_info"]
    note: str = Field(default="", max_length=500)
    override: bool = False


class AutopayIn(BaseModel):
    enable: bool


class DemoAccountIn(BaseModel):
    netbanking_enabled: Optional[bool] = None
    balance: Optional[float] = Field(default=None, ge=0, le=100_000_000)


class CalcIn(BaseModel):
    amount: float = Field(gt=0)
    annual_rate: float = Field(ge=0, le=40)
    tenure_months: int = Field(gt=0, le=480)


class ChatMsg(BaseModel):
    role: Literal["user", "assistant"]
    text: str = Field(max_length=2000)


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=1000)
    history: List[ChatMsg] = []


class RunAutopayIn(BaseModel):
    as_of: Optional[date] = None
    ignore_attempt_limit: bool = False


class ProfileUpdateIn(BaseModel):
    phone: str = Field(default="", pattern=r"^$|^[0-9]{10}$")
    address: str = Field(default="", max_length=250)
    city: str = Field(default="", max_length=60)
    pincode: str = Field(default="", pattern=r"^$|^[0-9]{6}$")
    employer: str = Field(default="", max_length=120)
    employment_type: Literal["SALARIED", "SELF_EMPLOYED"]
    monthly_income: float = Field(gt=0, le=10_000_000)
    existing_emi: float = Field(ge=0, le=10_000_000)   # EMIs with OTHER lenders


class PasswordIn(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=72)

    @field_validator("new_password")
    @classmethod
    def strong(cls, v):
        if not (any(c.isalpha() for c in v) and any(c.isdigit() for c in v)):
            raise ValueError("Password must contain letters and digits")
        return v


class SampleDocIn(BaseModel):
    doc_type: str

    @field_validator("doc_type")
    @classmethod
    def valid(cls, v):
        v = v.upper()
        if v not in DOC_TYPES:
            raise ValueError("Unknown document type")
        return v


class DocReviewIn(BaseModel):
    verdict: Literal["verify", "reject"]
    note: str = Field(default="", max_length=300)


class ReminderIn(BaseModel):
    message: str = Field(default="", max_length=500)


class RespondIn(BaseModel):
    status: Literal["IN_PROGRESS", "RESOLVED", "REJECTED"]
    response: str = Field(min_length=1, max_length=1000)


class DraftIn(BaseModel):
    goal: Literal["approve", "reject", "need_info"]


class ServiceRequestIn(BaseModel):
    category: Literal["PAYMENT", "LOAN", "DOCUMENT", "ACCOUNT", "AUTOPAY", "CLOSURE", "OTHER"]
    loan_id: Optional[int] = Field(default=None, gt=0)
    subject: str = Field(min_length=3, max_length=120)
    message: str = Field(min_length=5, max_length=1000)
