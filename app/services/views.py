import json

from .advisor import credit_tier
from .autopay import next_unpaid
from .eligibility import bank_obligations


def product_view(p):
    return {"code": p.code, "name": p.name, "min_amount": p.min_amount, "max_amount": p.max_amount,
            "min_tenure": p.min_tenure, "max_tenure": p.max_tenure, "base_rate": p.base_rate,
            "min_income": p.min_income, "min_credit_score": p.min_credit_score,
            "max_foir": p.max_foir, "max_ltv": p.max_ltv,
            "required_docs": [d for d in p.required_docs.split(",") if d]}


def account_view(a):
    return {"id": a.id, "account_no": a.account_no, "balance": a.balance,
            "netbanking_enabled": a.netbanking_enabled, "is_frozen": a.is_frozen,
            "daily_debit_limit": a.daily_debit_limit}


def inst_view(i):
    return {"number": i.number, "due_date": str(i.due_date), "emi": i.emi_amount,
            "principal": i.principal_part, "interest": i.interest_part, "status": i.status,
            "paid_on": str(i.paid_on) if i.paid_on else None, "attempts": i.attempts,
            "last_failure_code": i.last_failure_code}


def loan_view(l):
    nxt = next_unpaid(l)
    paid = sum(1 for i in l.installments if i.status == "PAID")
    return {"id": l.id, "product": l.product.code, "product_name": l.product.name,
            "principal": l.principal, "rate": l.rate, "tenure_months": l.tenure_months,
            "emi": l.emi, "outstanding": l.outstanding, "status": l.status,
            "autopay_enabled": l.autopay_enabled, "mandate_status": l.mandate_status,
            "mandate_limit": l.mandate_limit, "account_no": l.account.account_no,
            "next_due": inst_view(nxt) if nxt else None,
            "installments_paid": paid, "installments_total": len(l.installments),
            "disbursed_on": str(l.disbursed_on),
            "overdue_count": sum(1 for i in l.installments if i.status in ("OVERDUE", "FAILED"))}


def profile_view(db, user):
    from ..models import BankAccount, Loan
    p = user.profile
    bank_emi = bank_obligations(db, user.id)
    loans = db.query(Loan).filter_by(user_id=user.id, status="ACTIVE").all()
    total = p.existing_emi + bank_emi
    return {"id": user.id, "username": user.username, "full_name": user.full_name, "email": user.email,
            "role": user.role, "member_since": user.created_at.date().isoformat(),
            "dob": str(p.dob), "pan": p.pan[:2] + "XXXXX" + p.pan[-3:], "employment_type": p.employment_type,
            "employer": p.employer, "phone": p.phone, "address": p.address, "city": p.city,
            "pincode": p.pincode, "monthly_income": p.monthly_income, "kyc_verified": p.kyc_verified,
            "credit": credit_tier(p.credit_score),
            "obligations": {"other_lenders": p.existing_emi, "our_active_loans": bank_emi, "total": total,
                            "ratio": round(total / p.monthly_income, 4) if p.monthly_income else None},
            "active_loans": len(loans), "total_outstanding": round(sum(l.outstanding for l in loans), 2),
            "accounts": [account_view(a) for a in db.query(BankAccount).filter_by(user_id=user.id)]}


def app_view(a, officer_view=False):
    d = {"id": a.id, "product": a.product.code, "product_name": a.product.name,
         "amount": a.amount, "tenure_months": a.tenure_months, "purpose": a.purpose,
         "asset_value": a.asset_value, "docs": [x for x in a.docs.split(",") if x],
         "status": a.status, "rate": a.rate, "emi": a.emi, "foir": a.foir,
         "system_score": a.system_score, "system_recommendation": a.system_recommendation,
         "checks": json.loads(a.checks_json or "[]"), "officer_note": a.officer_note,
         "created_at": a.created_at.isoformat()}
    if officer_view:
        p = a.user.profile
        d["customer"] = {"id": a.user.id, "name": a.user.full_name, "email": a.user.email,
                         "income": p.monthly_income, "existing_emi": p.existing_emi,
                         "credit_score": p.credit_score, "employment": p.employment_type,
                         "kyc_verified": p.kyc_verified, "pan": p.pan[:2] + "XXXXX" + p.pan[-3:]}
        d["ai_summary"] = a.ai_summary
    return d
