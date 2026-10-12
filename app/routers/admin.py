from fastapi import APIRouter, Depends, HTTPException,Body
from sqlalchemy.orm import Session
import secrets
import string
from datetime import datetime, timezone
from ..database import get_db
from ..models import ADMIN, AuditLog, BankAccount, User,PasswordResetRequest,Notification
from ..schemas import RunAutopayIn, StaffCreateIn
from ..security import hash_password, require_roles
from ..services.autopay import run_autopay
from ..services.notify import audit

router = APIRouter(prefix="/api/admin", tags=["admin"])
admin = require_roles(ADMIN)


@router.get("/users")
def users(db: Session = Depends(get_db), user: User = Depends(admin)):
    return [{"id": u.id, "username": u.username, "full_name": u.full_name, "role": u.role,
             "is_active": u.is_active} for u in db.query(User).order_by(User.id)]


@router.post("/users/{uid}/reset-password")
def reset_customer_password(
    uid: int,
    db: Session = Depends(get_db),
    user: User = Depends(admin),
):
    """Admin resets a customer's password and receives a temporary password once."""

    customer = db.get(User, uid)

    if not customer or customer.role != "CUSTOMER":
        raise HTTPException(404, "Customer account not found")

    # Generate a temporary password with lowercase, uppercase and digits.
    alphabet = string.ascii_letters + string.digits
    chars = [
        secrets.choice(string.ascii_lowercase),
        secrets.choice(string.ascii_uppercase),
        secrets.choice(string.digits),
    ]
    chars.extend(secrets.choice(alphabet) for _ in range(13))
    secrets.SystemRandom().shuffle(chars)
    temporary_password = "".join(chars)

    # Use the project's existing password hashing function.
    customer.password_hash = hash_password(temporary_password)

    # Never include the temporary password in the audit log.
    audit(
        db,
        user.id,
        "CUSTOMER_PASSWORD_RESET",
        "user",
        customer.id,
        "Admin reset customer password",
    )

    db.commit()

    # Return the temporary password only in this response.
    return {
        "message": "Password reset successfully",
        "username": customer.username,
        "temporary_password": temporary_password,
    }

@router.post("/users")
def create_staff(d: StaffCreateIn, db: Session = Depends(get_db), user: User = Depends(admin)):
    if db.query(User).filter_by(username=d.username).first():
        raise HTTPException(409, "Username taken")
    u = User(username=d.username, full_name=d.full_name, email=d.email,
             password_hash=hash_password(d.password), role=d.role)
    db.add(u)
    db.flush()
    audit(db, user.id, "STAFF_CREATED", "user", u.id, d.role)
    db.commit()
    return {"id": u.id}


@router.post("/users/{uid}/toggle")
def toggle(uid: int, db: Session = Depends(get_db), user: User = Depends(admin)):
    u = db.get(User, uid)
    if not u or u.id == user.id:
        raise HTTPException(400, "Cannot change this user")
    u.is_active = not u.is_active
    audit(db, user.id, "USER_TOGGLED", "user", uid, str(u.is_active))
    db.commit()
    return {"is_active": u.is_active}



@router.get("/password-reset-requests")
def list_password_reset_requests(
    db: Session = Depends(get_db),
    user: User = Depends(admin),
):
    requests = (
        db.query(PasswordResetRequest)
        .order_by(PasswordResetRequest.id.desc())
        .all()
    )

    return [
        {
            "id": r.id,
            "username": db.get(User, r.user_id).username
                if db.get(User, r.user_id) else "Unknown",
            "status": r.status,
            "created_at": r.created_at.isoformat()
                if r.created_at else None,
            "reviewed_at": r.reviewed_at.isoformat()
                if r.reviewed_at else None,
        }
        for r in requests
    ]

@router.post("/password-reset-requests/{request_id}/review")
def review_password_reset_request(
    request_id: int,
    status: str = Body(..., embed=True),
    db: Session = Depends(get_db),
    user: User = Depends(admin),
):
    status = status.strip().upper()

    if status not in {"APPROVED", "REJECTED"}:
        raise HTTPException(
            400, "Status must be APPROVED or REJECTED"
        )

    request = db.get(PasswordResetRequest, request_id)

    if not request:
        raise HTTPException(404, "Reset request not found")

    if request.status != "PENDING":
        raise HTTPException(409, "Request has already been reviewed")

    customer = db.get(User, request.user_id)

    if not customer or customer.role != "CUSTOMER":
        raise HTTPException(404, "Customer account not found")

    request.status = status
    request.reviewed_at = datetime.now(timezone.utc).replace(tzinfo=None)
    request.reviewed_by = user.id

    response = {"message": f"Request {status.lower()}."}

    if status == "APPROVED":
        alphabet = string.ascii_letters + string.digits
        chars = [
            secrets.choice(string.ascii_lowercase),
            secrets.choice(string.ascii_uppercase),
            secrets.choice(string.digits),
        ]
        chars.extend(secrets.choice(alphabet) for _ in range(13))
        secrets.SystemRandom().shuffle(chars)

        temporary_password = "".join(chars)
        customer.password_hash = hash_password(temporary_password)

        response["temporary_password"] = temporary_password
        response["message"] = (
            "Request approved. Share the temporary password "
            "with the verified customer through a trusted channel."
        )

    db.add(Notification(
        user_id=customer.id,
        title="Password Reset Request Update",
        message=(
            "Your password reset request was approved. "
            "Contact the administrator through the app's "
            "approved support process to receive reset instructions."
            if status == "APPROVED"
            else "Your password reset request was rejected. "
                 "Please submit a new request if you still need help."
        ),
        kind="PASSWORD_RESET",
    ))

    audit(
        db,
        user.id,
        "PASSWORD_RESET_REQUEST_REVIEWED",
        "password_reset_request",
        request.id,
        f"Status: {status}; customer ID: {customer.id}",
    )

    db.commit()
    return response


@router.post("/accounts/{acc_id}/freeze")
def freeze(acc_id: int, db: Session = Depends(get_db), user: User = Depends(admin)):
    a = db.get(BankAccount, acc_id)
    if not a:
        raise HTTPException(404, "Not found")
    a.is_frozen = not a.is_frozen
    audit(db, user.id, "ACCOUNT_FREEZE_TOGGLED", "account", acc_id, str(a.is_frozen))
    db.commit()
    return {"is_frozen": a.is_frozen}


@router.post("/run-autopay")
def run(d: RunAutopayIn, db: Session = Depends(get_db), user: User = Depends(admin)):
    res = run_autopay(db, d.as_of, d.ignore_attempt_limit)
    audit(db, user.id, "AUTOPAY_RUN", "system", None, f"{len(res)} items")
    db.commit()
    return {"processed": len(res), "results": res}


@router.get("/audit")
def audit_log(db: Session = Depends(get_db), user: User = Depends(admin)):
    rows = db.query(AuditLog).order_by(AuditLog.id.desc()).limit(100).all()
    return [{"id": r.id, "actor_id": r.actor_id, "action": r.action, "entity": r.entity,
             "entity_id": r.entity_id, "detail": r.detail, "at": r.created_at.isoformat()} for r in rows]


@router.get("/accounts")
def accounts(db: Session = Depends(get_db), user: User = Depends(admin)):
    """List customer bank accounts for authorized administrators."""
    rows = db.query(BankAccount, User).join(User, User.id == BankAccount.user_id).all()
    return [
        {
            "id": account.id,
            "customer": customer.full_name,
            "account_no": account.account_no,
            "balance": account.balance,
            "netbanking_enabled": account.netbanking_enabled,
            "is_frozen": account.is_frozen,
        }
        for account, customer in rows
    ]
