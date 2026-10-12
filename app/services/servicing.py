"""Post-disbursal servicing: prepayment, foreclosure, statements, service requests, reminders."""
import csv
import io
import math
from datetime import date

from ..models import OFFICER, Installment, Loan, Payment, ServiceRequest, utcnow
from .autopay import DONE, diagnose, next_unpaid
from .emi import build_schedule
from .lifecycle import BusinessError
from .notify import audit, notify, notify_role


def remaining(loan):
    return [i for i in loan.installments if i.status not in DONE]


def months_needed(principal, rate, emi):
    r = rate / 1200.0
    if r == 0:
        return math.ceil(principal / emi)
    if emi <= principal * r:
        return None
    return max(1, math.ceil(-math.log(1 - r * principal / emi) / math.log(1 + r)))


def simulate_prepay(loan, amount):
    rem = remaining(loan)
    if loan.status != "ACTIVE" or not rem:
        raise BusinessError("Loan is not active")
    if amount <= 0:
        raise BusinessError("Amount must be positive")
    out = loan.outstanding
    old_interest = round(sum(i.interest_part for i in rem), 2)
    if amount >= out:
        return {"type": "FORECLOSURE", "payable": out, "interest_saved": old_interest,
                "remaining_emis": len(rem)}
    new_out, first, n = round(out - amount, 2), rem[0].due_date, len(rem)
    a = build_schedule(new_out, loan.rate, n, first)
    n2 = min(months_needed(new_out, loan.rate, loan.emi) or n, n)
    b = build_schedule(new_out, loan.rate, n2, first)
    tot = lambda rows: round(sum(r["interest_part"] for r in rows), 2)  # noqa: E731
    return {"type": "PART_PREPAYMENT", "payable": amount, "new_outstanding": new_out,
            "current_emi": loan.emi, "current_months_left": n,
            "reduce_emi": {"emi": a[0]["emi_amount"], "months": n, "interest_saved": round(old_interest - tot(a), 2)},
            "reduce_tenure": {"emi": b[0]["emi_amount"], "months": n2, "interest_saved": round(old_interest - tot(b), 2)}}


def _check_account(loan, amount):
    acct = loan.account
    if acct.is_frozen:
        raise BusinessError("Account is frozen - visit your branch")
    if acct.balance < amount:
        raise BusinessError(f"Balance Rs {acct.balance:,.2f} is below the required Rs {amount:,.2f}")
    return acct


def foreclose(db, loan, actor_id):
    rem = remaining(loan)
    if loan.status != "ACTIVE" or not rem:
        raise BusinessError("Loan is not active")
    amount = loan.outstanding
    acct = _check_account(loan, amount)
    for i in rem:
        i.status, i.paid_on = "PRECLOSED", date.today()
    acct.balance = round(acct.balance - amount, 2)
    loan.status, loan.outstanding = "CLOSED", 0.0
    db.add(Payment(loan_id=loan.id, amount=amount, mode="FORECLOSE", status="SUCCESS"))
    notify(db, loan.user_id, f"Loan #{loan.id} closed",
           f"Foreclosed with Rs {amount:,.2f}. Request an NOC from Requests if needed.", "LOAN")
    audit(db, actor_id, "LOAN_FORECLOSED", "loan", loan.id, f"{amount:,.2f}")
    db.commit()
    return {"type": "FORECLOSURE", "paid": amount}


def prepay(db, loan, amount, option, actor_id):
    sim = simulate_prepay(loan, amount)
    if sim["type"] == "FORECLOSURE":
        return foreclose(db, loan, actor_id)
    if option not in ("reduce_emi", "reduce_tenure"):
        raise BusinessError("option must be reduce_emi or reduce_tenure")
    rem = remaining(loan)
    if any(i.status in ("FAILED", "OVERDUE") or i.due_date < date.today() for i in rem):
        raise BusinessError("Clear your overdue EMI(s) before prepaying")
    acct = _check_account(loan, amount)
    chosen = sim[option]
    start, first = rem[0].number, rem[0].due_date
    rows = build_schedule(sim["new_outstanding"], loan.rate, chosen["months"], first)
    for i in rem:
        db.delete(i)
    db.flush()
    for k, r in enumerate(rows):
        db.add(Installment(loan_id=loan.id, **{**r, "number": start + k}))
    acct.balance = round(acct.balance - amount, 2)
    loan.tenure_months -= len(rem) - chosen["months"]
    loan.outstanding, loan.emi = sim["new_outstanding"], rows[0]["emi_amount"]
    if loan.autopay_enabled:
        loan.mandate_limit = round(loan.emi * 1.25, 2)
    db.add(Payment(loan_id=loan.id, amount=amount, mode="PREPAY", status="SUCCESS"))
    notify(db, loan.user_id, f"Prepayment of Rs {amount:,.2f} received",
           f"New EMI Rs {loan.emi:,.2f}, {chosen['months']} EMIs left. Interest saved ~Rs {chosen['interest_saved']:,.2f}.", "PAYMENT")
    audit(db, actor_id, "LOAN_PREPAID", "loan", loan.id, f"{amount:,.2f} {option}")
    db.commit()
    db.expire(loan, ["installments"])
    return {**sim, "applied": option}


def statement_csv(loan, payments):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Loan statement", f"#{loan.id}", loan.product.name, f"Rate {loan.rate}%",
                f"Principal {loan.principal}", f"Outstanding {loan.outstanding}", loan.status])
    w.writerow([])
    w.writerow(["EMI #", "Due date", "EMI", "Principal", "Interest", "Status", "Paid on"])
    for i in loan.installments:
        w.writerow([i.number, i.due_date, i.emi_amount, i.principal_part, i.interest_part, i.status, i.paid_on or ""])
    w.writerow([])
    w.writerow(["Date", "Mode", "Status", "Amount", "EMI #", "Failure reason"])
    nums = {i.id: i.number for i in loan.installments}
    for p in payments:
        w.writerow([p.created_at.isoformat(timespec="seconds"), p.mode, p.status, p.amount,
                    nums.get(p.installment_id, ""), p.failure_code or ""])
    return buf.getvalue()


def create_request(db, user, data):
    if data.loan_id is not None and not db.query(Loan).filter_by(id=data.loan_id, user_id=user.id).first():
        raise BusinessError("Loan not found")
    r = ServiceRequest(user_id=user.id, loan_id=data.loan_id, category=data.category,
                       subject=data.subject, message=data.message)
    db.add(r)
    db.flush()
    audit(db, user.id, "REQUEST_RAISED", "request", r.id, data.category)
    notify(db, user.id, f"Request #{r.id} received", f"{data.category}: {data.subject}", "REQUEST")
    notify_role(db, OFFICER, f"New service request #{r.id}", f"{user.full_name}: {data.category} - {data.subject}", "REQUEST")
    db.commit()
    return r


def respond_request(db, officer, r, status, response):
    r.status, r.response, r.handled_by = status, response, officer.id
    r.resolved_at = utcnow() if status in ("RESOLVED", "REJECTED") else None
    notify(db, r.user_id, f"Request #{r.id} {status.replace('_', ' ').lower()}", response, "REQUEST")
    audit(db, officer.id, f"REQUEST_{status}", "request", r.id, response)
    db.commit()
    return r


def req_view(r, with_customer=False):
    d = {"id": r.id, "category": r.category, "subject": r.subject, "message": r.message,
         "status": r.status, "response": r.response, "loan_id": r.loan_id,
         "created_at": r.created_at.isoformat(timespec="seconds")}
    if with_customer:
        d["customer"] = r.user.full_name
        d["customer_id"] = r.user_id
    return d


def send_reminder(db, officer, loan, message=""):
    inst = next_unpaid(loan)
    if loan.status != "ACTIVE" or not inst:
        raise BusinessError("Loan has nothing due")
    if not message:
        d = diagnose(loan, inst, loan.account)
        message = (f"EMI #{inst.number} of Rs {inst.emi_amount:,.2f} was due on {inst.due_date}. "
                   + (d["message"] + " " + (d["steps"][0] if d["steps"] else "") if d else "Please pay now."))
    notify(db, loan.user_id, "Payment reminder from your bank", message, "REMINDER")
    audit(db, officer.id, "REMINDER_SENT", "loan", loan.id, message[:200])
    db.commit()
    return message
