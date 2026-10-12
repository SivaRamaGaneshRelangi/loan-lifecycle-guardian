import csv
import io

from fastapi import APIRouter, Depends, Body, File, Form, HTTPException, Response, UploadFile
from sqlalchemy.orm import Session
from ..services.insights import customer_insights
from ..config import settings
from ..database import get_db
from ..models import (CUSTOMER,ADMIN, BankAccount,PasswordResetRequest, Document, Loan, LoanApplication, LoanProduct, Notification,
                      Payment, ServiceRequest, User)
from ..schemas import (ApplicationIn, AutopayIn, CalcIn, DemoAccountIn, PasswordIn, ProfileUpdateIn,
                       SampleDocIn, ServiceRequestIn)
from ..security import get_current_user, hash_password, require_roles, verify_password
from ..services import advisor, documents, llm
from ..services.autopay import diagnose, next_unpaid
from ..services.emi import calc_emi
from ..services.lifecycle import (create_application, foreclose, manual_pay, precheck,
                                  resubmit, revalidate_open, set_autopay)
from ..services.notify import audit
from ..services.views import account_view, app_view, inst_view, loan_view, product_view, profile_view

router = APIRouter(prefix="/api", tags=["customer"])
cust = require_roles(CUSTOMER)

@router.post("/auth/password-reset-requests")
def create_password_reset_request(
    username: str = Body(..., embed=True),
    db: Session = Depends(get_db),
):
    # Always return the same message to avoid revealing
    # whether a username exists.
    message = (
        "If the account exists, a password reset request "
        "has been submitted for review."
    )

    customer = (
        db.query(User)
        .filter_by(username=username.strip(), role=CUSTOMER)
        .first()
    )

    if not customer:
        return {"message": message}

    # Avoid multiple pending requests for the same customer.
    existing = (
        db.query(PasswordResetRequest)
        .filter_by(user_id=customer.id, status="PENDING")
        .first()
    )

    if existing:
        return {"message": message}

    request = PasswordResetRequest(user_id=customer.id)
    db.add(request)
    db.flush()

    # Notify every active administrator in the dashboard.
    admins = (
        db.query(User)
        .filter_by(role=ADMIN, is_active=True)
        .all()
    )

    for admin_user in admins:
        db.add(Notification(
            user_id=admin_user.id,
            title="Password Reset Request",
            message=(
                f"Customer {customer.username} submitted "
                f"password reset request #{request.id}."
            ),
            kind="PASSWORD_RESET",
        ))

    db.commit()
    return {"message": message}


def _loan(db, user, loan_id) -> Loan:
    l = db.query(Loan).filter_by(id=loan_id, user_id=user.id).first()
    if not l:
        raise HTTPException(404, "Loan not found")
    return l


@router.get("/products")
def products(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return [product_view(p) for p in db.query(LoanProduct).filter_by(active=True)]


@router.post("/emi/calc")
def emi_calc(d: CalcIn, user: User = Depends(get_current_user)):
    emi = calc_emi(d.amount, d.annual_rate, d.tenure_months)
    return {"emi": emi, "total_payable": round(emi * d.tenure_months, 2),
            "total_interest": round(emi * d.tenure_months - d.amount, 2)}


@router.get("/me/accounts")
def accounts(db: Session = Depends(get_db), user: User = Depends(cust)):
    return [account_view(a) for a in db.query(BankAccount).filter_by(user_id=user.id)]


@router.post("/me/accounts/demo")
def demo_account(d: DemoAccountIn, db: Session = Depends(get_db), user: User = Depends(cust)):
    """Sandbox switches so you can demo failure reasons. Disabled when DEMO_MODE=0."""
    if not settings.DEMO_MODE:
        raise HTTPException(403, "Demo mode is off")
    a = db.query(BankAccount).filter_by(user_id=user.id).first()
    if d.netbanking_enabled is not None:
        a.netbanking_enabled = d.netbanking_enabled
    if d.balance is not None:
        a.balance = d.balance
    db.commit()
    return account_view(a)


@router.get("/me/loans")
def my_loans(db: Session = Depends(get_db), user: User = Depends(cust)):
    return [loan_view(l) for l in db.query(Loan).filter_by(user_id=user.id).order_by(Loan.id)]


@router.get("/me/loans/{loan_id}/schedule")
def schedule(loan_id: int, db: Session = Depends(get_db), user: User = Depends(cust)):
    return [inst_view(i) for i in _loan(db, user, loan_id).installments]


@router.get("/me/loans/{loan_id}/autopay-status")
def autopay_status(loan_id: int, explain: bool = False, db: Session = Depends(get_db),
                   user: User = Depends(cust)):
    l = _loan(db, user, loan_id)
    inst = next_unpaid(l)
    if not inst:
        return {"ok": True, "message": "Loan fully paid."}
    d = diagnose(l, inst, l.account)
    if not d:
        return {"ok": True, "message": "Auto-pay is set up correctly for your next EMI."}
    d["ok"] = False
    if explain:
        text = llm.generate(
            "Explain this EMI auto-debit problem to a bank customer in under 90 words, friendly, "
            "then list the steps. Do not invent facts.\nDATA: " + str(d),
            system="You are a careful retail-banking support assistant.")
        d["ai_explanation"] = text
    return d


@router.post("/me/loans/{loan_id}/autopay")
def autopay(loan_id: int, d: AutopayIn, db: Session = Depends(get_db), user: User = Depends(cust)):
    return loan_view(set_autopay(db, _loan(db, user, loan_id), d.enable, user.id))


@router.post("/me/loans/{loan_id}/pay")
def pay(loan_id: int, db: Session = Depends(get_db), user: User = Depends(cust)):
    inst = manual_pay(db, _loan(db, user, loan_id), user.id)
    return {"paid_installment": inst.number, "amount": inst.emi_amount}

@router.get("/me/insights")
def my_insights(
    db: Session = Depends(get_db),
    user: User = Depends(cust),
):
    """Return proactive alerts for the logged-in customer."""
    return customer_insights(db, user)

@router.post("/me/applications/precheck")
def app_precheck(d: ApplicationIn, db: Session = Depends(get_db), user: User = Depends(cust)):
    return precheck(db, user, d)


@router.post("/me/applications")
def apply(d: ApplicationIn, db: Session = Depends(get_db), user: User = Depends(cust)):
    return app_view(create_application(db, user, d))


@router.get("/me/applications")
def my_apps(db: Session = Depends(get_db), user: User = Depends(cust)):
    rows = db.query(LoanApplication).filter_by(user_id=user.id).order_by(LoanApplication.id.desc())
    return [app_view(a) for a in rows]


@router.post("/me/applications/{app_id}/resubmit")
def resubmit_app(app_id: int, db: Session = Depends(get_db), user: User = Depends(cust)):
    a = db.get(LoanApplication, app_id)
    if not a or a.user_id != user.id:
        raise HTTPException(404, "Application not found")
    resubmit(db, user, a)
    return app_view(a)


# ---------- profile ----------
@router.get("/me/profile")
def get_profile(db: Session = Depends(get_db), user: User = Depends(cust)):
    return profile_view(db, user)


@router.put("/me/profile")
def update_profile(d: ProfileUpdateIn, db: Session = Depends(get_db), user: User = Depends(cust)):
    p = user.profile
    old = f"income {p.monthly_income:,.0f}->{d.monthly_income:,.0f}, other EMI {p.existing_emi:,.0f}->{d.existing_emi:,.0f}"
    for k, v in d.model_dump().items():
        setattr(p, k, v)
    audit(db, user.id, "PROFILE_UPDATED", "user", user.id, old)
    revalidate_open(db, user.id)  # open applications must see the new figures
    db.commit()
    return profile_view(db, user)


@router.post("/me/password")
def change_password(d: PasswordIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if not verify_password(d.current_password, user.password_hash):
        raise HTTPException(400, "Current password is wrong")
    user.password_hash = hash_password(d.new_password)
    audit(db, user.id, "PASSWORD_CHANGED", "user", user.id)
    db.commit()
    return {"ok": True}


# ---------- AI loan-fit ----------
@router.get("/me/loan-fit")
def loan_fit(explain: bool = True, db: Session = Depends(get_db), user: User = Depends(cust)):
    res = advisor.loan_fit(db, user)
    if explain:
        res["narrative"], res["narrative_mode"] = advisor.narrate(res, user)
    return res


# ---------- document locker ----------
@router.get("/me/documents")
def my_documents(db: Session = Depends(get_db), user: User = Depends(cust)):
    rows = db.query(Document).filter_by(user_id=user.id).order_by(Document.id.desc()).all()
    return {"documents": [documents.doc_view(d) for d in rows],
            "types": [{"code": k, "label": v} for k, v in documents.DOC_LABELS.items()],
            "required_by_product": {p.code: [d for d in p.required_docs.split(",") if d]
                                    for p in db.query(LoanProduct).filter_by(active=True)},
            "max_mb": settings.MAX_UPLOAD_MB, "demo": settings.DEMO_MODE}


@router.post("/me/documents")
def upload_document(doc_type: str = Form(...), file: UploadFile = File(...),
                    db: Session = Depends(get_db), user: User = Depends(cust)):
    content = file.file.read(settings.MAX_UPLOAD_MB * 1024 * 1024 + 1)
    doc = documents.store(db, user, doc_type, file.filename, content)
    revalidate_open(db, user.id)
    db.commit()
    return documents.doc_view(doc)


@router.post("/me/documents/sample")
def sample_document(d: SampleDocIn, db: Session = Depends(get_db), user: User = Depends(cust)):
    if not settings.DEMO_MODE:
        raise HTTPException(403, "Demo mode is off")
    doc = documents.make_sample(db, user, d.doc_type)
    revalidate_open(db, user.id)
    db.commit()
    return documents.doc_view(doc)


def _own_doc(db, user, doc_id):
    d = db.query(Document).filter_by(id=doc_id, user_id=user.id).first()
    if not d:
        raise HTTPException(404, "Document not found")
    return d


@router.get("/me/documents/{doc_id}/file")
def download_document(doc_id: int, db: Session = Depends(get_db), user: User = Depends(cust)):
    d = _own_doc(db, user, doc_id)
    path = documents.file_path(d)
    if not path.exists():
        raise HTTPException(404, "File missing on server")
    return Response(path.read_bytes(), media_type=d.content_type,
                    headers={"Content-Disposition": f'inline; filename="{d.filename}"',
                             "X-Content-Type-Options": "nosniff"})


@router.delete("/me/documents/{doc_id}")
def delete_document(doc_id: int, db: Session = Depends(get_db), user: User = Depends(cust)):
    documents.remove(db, user, _own_doc(db, user, doc_id))
    db.flush()
    revalidate_open(db, user.id)
    db.commit()
    return {"ok": True}


# ---------- loan extras ----------
@router.post("/me/loans/{loan_id}/foreclose")
def foreclose_loan(loan_id: int, db: Session = Depends(get_db), user: User = Depends(cust)):
    return {"paid": foreclose(db, _loan(db, user, loan_id), user.id)}


@router.get("/me/loans/{loan_id}/payments")
def loan_payments(loan_id: int, db: Session = Depends(get_db), user: User = Depends(cust)):
    _loan(db, user, loan_id)
    rows = db.query(Payment).filter_by(loan_id=loan_id).order_by(Payment.id.desc()).all()
    return [{"id": p.id, "amount": p.amount, "mode": p.mode, "status": p.status,
             "failure_code": p.failure_code, "at": p.created_at.isoformat()} for p in rows]


@router.get("/me/loans/{loan_id}/statement.csv")
def statement(loan_id: int, db: Session = Depends(get_db), user: User = Depends(cust)):
    l = _loan(db, user, loan_id)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Loan", l.id, l.product.name, "Principal", l.principal, "Rate %", l.rate])
    w.writerow(["No", "Due date", "EMI", "Principal", "Interest", "Status", "Paid on"])
    for i in l.installments:
        w.writerow([i.number, i.due_date, i.emi_amount, i.principal_part, i.interest_part, i.status, i.paid_on or ""])
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="loan_{l.id}_statement.csv"'})


@router.get("/me/notifications")
def notifications(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = (db.query(Notification).filter_by(user_id=user.id)
            .order_by(Notification.id.desc()).limit(50).all())
    return [{"id": n.id, "title": n.title, "message": n.message, "kind": n.kind,
             "is_read": n.is_read, "created_at": n.created_at.isoformat()} for n in rows]


@router.post("/me/notifications/read")
def mark_read(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    db.query(Notification).filter_by(user_id=user.id, is_read=False).update({"is_read": True})
    db.commit()
    return {"ok": True}


@router.get("/me/requests")
def my_requests(db: Session = Depends(get_db), user: User = Depends(cust)):
    from ..services.servicing import req_view
    rows = db.query(ServiceRequest).filter_by(user_id=user.id).order_by(ServiceRequest.id.desc()).all()
    return [req_view(r) for r in rows]


@router.post("/me/requests")
def create_my_request(d: ServiceRequestIn, db: Session = Depends(get_db), user: User = Depends(cust)):
    from ..services.servicing import create_request
    from ..services.lifecycle import BusinessError
    try:
        request = create_request(db, user, d)
    except BusinessError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"id": request.id, "status": request.status}
