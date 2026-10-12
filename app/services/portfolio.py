from datetime import date

from sqlalchemy import func

from ..models import Installment, Loan, LoanApplication, LoanProduct, Payment, ServiceRequest


def dashboard(db):
    apps = dict(db.query(LoanApplication.status, func.count(LoanApplication.id)).group_by(LoanApplication.status).all())
    recs = dict(db.query(LoanApplication.system_recommendation, func.count(LoanApplication.id))
                .filter(LoanApplication.status.in_(["SUBMITTED", "NEED_INFO"]))
                .group_by(LoanApplication.system_recommendation).all())
    n, out = db.query(func.count(Loan.id), func.coalesce(func.sum(Loan.outstanding), 0)).filter(Loan.status == "ACTIVE").one()
    on, oa = (db.query(func.count(Installment.id), func.coalesce(func.sum(Installment.emi_amount), 0))
              .join(Loan, Loan.id == Installment.loan_id)
              .filter(Loan.status == "ACTIVE", Installment.status.in_(["FAILED", "OVERDUE"])).one())
    ok = db.query(func.count(Payment.id)).filter(Payment.mode == "AUTOPAY", Payment.status == "SUCCESS").scalar()
    bad = db.query(func.count(Payment.id)).filter(Payment.mode == "AUTOPAY", Payment.status == "FAILED").scalar()
    reqs = db.query(func.count(ServiceRequest.id)).filter(ServiceRequest.status.in_(["OPEN", "IN_PROGRESS"])).scalar()
    byp = (db.query(LoanProduct.code, func.count(Loan.id), func.coalesce(func.sum(Loan.outstanding), 0))
           .join(Loan, Loan.product_id == LoanProduct.id).filter(Loan.status == "ACTIVE")
           .group_by(LoanProduct.code).all())
    return {"applications": apps, "queue_recommendations": recs, "active_loans": n,
            "total_outstanding": round(float(out), 2), "overdue_count": on, "overdue_amount": round(float(oa), 2),
            "autopay_success": ok, "autopay_failed": bad,
            "autopay_success_rate": round(100 * ok / (ok + bad), 1) if ok + bad else None,
            "open_requests": reqs,
            "by_product": [{"product": c, "loans": k, "outstanding": round(float(o), 2)} for c, k, o in byp]}


def collections(db, today=None):
    today = today or date.today()
    rows = (db.query(Installment).join(Loan, Loan.id == Installment.loan_id)
            .filter(Loan.status == "ACTIVE", Installment.status.in_(["PENDING", "FAILED", "OVERDUE"]),
                    Installment.due_date <= today).order_by(Installment.due_date).all())
    return [{"loan_id": i.loan_id, "customer": i.loan.user.full_name, "product": i.loan.product.code,
             "installment": i.number, "due_date": str(i.due_date), "days_overdue": (today - i.due_date).days,
             "amount": i.emi_amount, "status": i.status, "autopay": i.loan.autopay_enabled,
             "last_failure_code": i.last_failure_code, "attempts": i.attempts} for i in rows]
