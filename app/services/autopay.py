"""Auto-debit engine + failure diagnosis (the 'why did my autopay fail' brain)."""
from datetime import date

from ..config import settings
from ..models import Installment, Loan, Payment
from .notify import notify

DONE = ("PAID", "CLOSED_EARLY")  # installment statuses that need no more collection

NETBANKING_PATH = {
    "HOME": "Net Banking > Loans > Home Loan > Manage Repayment > e-NACH Mandate",
    "PERSONAL": "Net Banking > Loans > Personal Loan > Auto-Debit (Standing Instruction)",
    "AUTO": "Net Banking > Loans > Vehicle Loan > Repayment Mandate",
    "EDUCATION": "Net Banking > Loans > Education Loan > Repayment Setup",
    "GOLD": "Net Banking > Loans > Gold Loan > Interest/EMI Auto-Debit",
}
TYPE_NOTE = {
    "HOME": "Home-loan mandates must be linked to your repayment account; if you changed your salary account, re-register the mandate.",
    "PERSONAL": "Personal loans carry higher bounce charges - keep one extra EMI as a buffer before the due date.",
    "AUTO": "Repeated bounces on a vehicle loan can trigger a recovery notice after 3 missed EMIs.",
    "EDUCATION": "Check whether you are still in the moratorium period - only interest may be due then.",
    "GOLD": "Unpaid gold-loan dues can lead to the pledged gold being auctioned after notice - pay quickly.",
}


def explain(code, loan, inst, acct):
    ptype = loan.product.code
    path = NETBANKING_PATH.get(ptype, "Net Banking > Loans")
    emi = inst.emi_amount
    mask = "XXXX" + acct.account_no[-4:] if acct else "-"
    steps, shortfall = [], 0.0
    if code == "INSUFFICIENT_BALANCE":
        shortfall = round(emi - acct.balance, 2)
        title = "Insufficient balance"
        msg = (f"Account {mask} has Rs {acct.balance:,.2f} but the EMI of Rs {emi:,.2f} is due "
               f"(short by Rs {shortfall:,.2f}).")
        steps = [f"Add at least Rs {shortfall:,.2f} (plus a small buffer) to account {mask}.",
                 "Or use 'Pay now' in the app to clear the EMI manually.",
                 f"Auto-debit retries on the next run (up to {settings.MAX_AUTOPAY_ATTEMPTS} attempts)."]
    elif code == "NETBANKING_DISABLED":
        title = "Net banking disabled"
        msg = ("Net banking / transaction rights are switched off on your account, so the bank cannot "
               "execute the e-mandate debit.")
        steps = [f"Go to {path}.", "Re-enable net banking (Security > Transaction rights) or visit the branch.",
                 "Re-authorise the mandate with the OTP sent to your registered mobile."]
    elif code == "MANDATE_NOT_ACTIVE":
        title = "Auto-pay mandate not active"
        msg = "No active auto-pay mandate exists for this loan, so nothing can be debited automatically."
        steps = [f"Enable auto-pay in the app or at {path}.", "Authorise with OTP.",
                 "Pay this EMI manually meanwhile to avoid late charges."]
    elif code == "MANDATE_LIMIT_EXCEEDED":
        title = "Mandate limit lower than EMI"
        msg = f"Your mandate limit is Rs {loan.mandate_limit:,.2f}, lower than the EMI of Rs {emi:,.2f}."
        steps = [f"Raise the mandate limit to at least Rs {emi:,.2f} at {path}."]
    elif code == "DAILY_LIMIT_EXCEEDED":
        title = "Daily debit limit exceeded"
        msg = f"The EMI of Rs {emi:,.2f} is above your account's daily debit limit of Rs {acct.daily_debit_limit:,.2f}."
        steps = ["Increase the daily transaction limit in Net Banking > Limits, then retry."]
    elif code == "ACCOUNT_FROZEN":
        title = "Account frozen"
        msg = f"Account {mask} is frozen, so debits are blocked."
        steps = ["Visit your branch with KYC documents to unfreeze the account.",
                 "Pay the EMI from another channel meanwhile."]
    else:
        title = "No linked account"
        msg = "No bank account is linked to this loan."
        steps = ["Link a savings account in your profile."]
    steps.append(TYPE_NOTE.get(ptype, ""))
    return {"code": code, "title": title, "message": msg, "netbanking_path": path,
            "steps": [s for s in steps if s], "shortfall": shortfall}


def diagnose(loan, inst, acct):
    """Return an explanation dict if an auto-debit of `inst` would fail now, else None."""
    emi = inst.emi_amount
    if acct is None:
        code = "NO_ACCOUNT"
    elif acct.is_frozen:
        code = "ACCOUNT_FROZEN"
    elif not loan.autopay_enabled or loan.mandate_status != "ACTIVE":
        code = "MANDATE_NOT_ACTIVE"
    elif not acct.netbanking_enabled:
        code = "NETBANKING_DISABLED"
    elif emi > loan.mandate_limit:
        code = "MANDATE_LIMIT_EXCEEDED"
    elif emi > acct.daily_debit_limit:
        code = "DAILY_LIMIT_EXCEEDED"
    elif acct.balance < emi:
        code = "INSUFFICIENT_BALANCE"
    else:
        return None
    return explain(code, loan, inst, acct)


def settle(db, loan, inst, mode, on=None):
    acct = loan.account
    acct.balance = round(acct.balance - inst.emi_amount, 2)
    inst.status, inst.paid_on, inst.last_failure_code = "PAID", on or date.today(), None
    loan.outstanding = max(0.0, round(loan.outstanding - inst.principal_part, 2))
    db.add(Payment(loan_id=loan.id, installment_id=inst.id, amount=inst.emi_amount,
                   mode=mode, status="SUCCESS"))
    db.flush()
    if not any(i.status not in DONE for i in loan.installments):
        loan.status, loan.outstanding = "CLOSED", 0.0
    notify(db, loan.user_id, f"EMI #{inst.number} paid",
           f"Rs {inst.emi_amount:,.2f} debited from XXXX{acct.account_no[-4:]} ({mode.lower()}).", "PAYMENT")


def next_unpaid(loan):
    return next((i for i in loan.installments if i.status not in DONE), None)


def run_autopay(db, as_of=None, ignore_attempt_limit=False):
    as_of = as_of or date.today()
    due = (db.query(Installment).join(Loan, Loan.id == Installment.loan_id)
           .filter(Loan.status == "ACTIVE", Installment.due_date <= as_of,
                   Installment.status.in_(["PENDING", "FAILED", "OVERDUE"]))
           .order_by(Installment.due_date, Installment.number).all())
    results = []
    for inst in due:
        loan = inst.loan
        # Row locks (no-op on SQLite, real on SQL Server/Postgres) + re-read: a concurrent run
        # (scheduler vs admin button) must not debit the same instalment twice.
        db.refresh(inst, with_for_update=True)
        if inst.status in DONE:
            continue
        if loan.account is not None:
            db.refresh(loan.account, with_for_update=True)
        nxt = next_unpaid(loan)
        if nxt is None or nxt.id != inst.id:
            continue  # strictly oldest-first
        row = {"loan_id": loan.id, "customer": loan.user.full_name, "installment": inst.number,
               "amount": inst.emi_amount}
        if not loan.autopay_enabled:
            inst.status = "OVERDUE" if inst.due_date < as_of else "PENDING"
            if inst.last_notified_on != as_of:
                notify(db, loan.user_id, f"EMI #{inst.number} due",
                       f"Rs {inst.emi_amount:,.2f} is due on {inst.due_date}. Auto-pay is OFF - pay now or enable auto-pay.",
                       "REMINDER")
                inst.last_notified_on = as_of
            results.append({**row, "result": "REMINDER_SENT", "code": "AUTOPAY_OFF"})
            continue
        if inst.attempts >= settings.MAX_AUTOPAY_ATTEMPTS and not ignore_attempt_limit:
            results.append({**row, "result": "SKIPPED_MAX_ATTEMPTS", "code": inst.last_failure_code})
            continue
        inst.attempts += 1
        diag = diagnose(loan, inst, loan.account)
        if diag is None:
            settle(db, loan, inst, "AUTOPAY", on=as_of)
            results.append({**row, "result": "PAID", "code": None})
        else:
            inst.status = "OVERDUE" if inst.due_date < as_of else "FAILED"
            inst.last_failure_code = diag["code"]
            db.add(Payment(loan_id=loan.id, installment_id=inst.id, amount=inst.emi_amount,
                           mode="AUTOPAY", status="FAILED", failure_code=diag["code"]))
            if inst.last_notified_on != as_of:
                notify(db, loan.user_id, f"Auto-debit failed: {diag['title']}",
                       diag["message"] + " Next: " + " | ".join(diag["steps"][:2]), "AUTOPAY_FAILED")
                inst.last_notified_on = as_of
            results.append({**row, "result": "FAILED", "code": diag["code"]})
    db.commit()
    return results
