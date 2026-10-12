import random
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import CUSTOMER, BankAccount, CustomerProfile, User
from ..schemas import LoginIn, RegisterIn
from ..security import create_token, get_current_user, hash_password, verify_password
from ..services.eligibility import bureau_score
from ..services.notify import audit

router = APIRouter(prefix="/api/auth", tags=["auth"])
_fails = {}  # (username, client ip) -> (count, first_ts); in-memory - use Redis/DB with several workers


def user_view(u):
    return {"id": u.id, "username": u.username, "full_name": u.full_name, "email": u.email, "role": u.role}


@router.post("/register")
def register(data: RegisterIn, db: Session = Depends(get_db)):
    if db.query(User).filter_by(username=data.username).first():
        raise HTTPException(409, "Username already taken")
    u = User(username=data.username, full_name=data.full_name, email=data.email,
             password_hash=hash_password(data.password), role=CUSTOMER)
    db.add(u)
    db.flush()
    db.add(CustomerProfile(user_id=u.id, dob=data.dob, pan=data.pan, monthly_income=data.monthly_income,
                           existing_emi=data.existing_emi, credit_score=bureau_score(data.pan),
                           employment_type=data.employment_type, kyc_verified=False,
                           phone=data.phone, address=data.address, city=data.city, pincode=data.pincode))
    db.add(BankAccount(user_id=u.id, account_no="5010" + "".join(random.choices("0123456789", k=10)),
                       balance=0))
    audit(db, u.id, "REGISTER", "user", u.id)
    db.commit()
    return {"token": create_token(u), "user": user_view(u)}


@router.post("/login")
def login(data: LoginIn, request: Request, db: Session = Depends(get_db)):
    key = (data.username, request.client.host if request.client else "?")
    cnt, ts = _fails.get(key, (0, time.time()))
    if cnt and time.time() - ts >= 300:
        cnt, ts = 0, time.time()
    if cnt >= 5 and time.time() - ts < 300:
        raise HTTPException(429, "Too many failed attempts. Try again in 5 minutes.")
    u = db.query(User).filter_by(username=data.username).first()
    if not u or not u.is_active or not verify_password(data.password, u.password_hash):
        _fails[key] = (cnt + 1, ts if cnt else time.time())
        raise HTTPException(401, "Invalid credentials")
    _fails.pop(key, None)
    audit(db, u.id, "LOGIN", "user", u.id)
    db.commit()
    return {"token": create_token(u), "user": user_view(u)}


@router.get("/me")
def me(user: User = Depends(get_current_user)):
    return user_view(user)
