import json
from datetime import date, datetime

from ..models import (OFFICER, OPEN_APP_STATUSES, BankAccount, Installment, Loan,
                      LoanApplication, LoanProduct, Payment, utcnow)
from . import documents
from .autopay import DONE, next_unpaid, settle
from .eligibility import bank_obligations, evaluate
from .emi import add_months, build_schedule
from .errors import BusinessError  # noqa: F401  (re-exported for other modules)
from .notify import audit, notify, notify_role


def _context(db, user_id):
    """Facts the bank knows itself: documents in the locker and EMIs of our own active loans."""
    docs, pending = documents.received(db, user_id)
    return docs, pending, bank_obligations(db, user_id)


def _resolve(db, user, product_code):
    product = db.query(LoanProduct).filter_by(code=product_code.upper(), active=True).first()
    if not product:
        raise BusinessError(f"Unknown loan product '{product_code}'")
    if not user.profile:
        raise BusinessError("Customer profile missing")
    return product, user.profile


def precheck(db, user, data):
    product, profile = _resolve(db, user, data.product_code)
    docs, pending, bank_emi = _context(db, user.id)
    return evaluate(profile, product, data.amount, data.tenure_months, data.asset_value, docs,
                    bank_emi=bank_emi, pending_docs=pending)


def create_application(db, user, data):
    product, profile = _resolve(db, user, data.product_code)
    if not db.query(BankAccount).filter_by(user_id=user.id).first():
        raise BusinessError("Link a bank account before applying")
    dup = db.query(LoanApplication).filter(
        LoanApplication.user_id == user.id, LoanApplication.product_id == product.id,
        LoanApplication.status.in_(OPEN_APP_STATUSES)).first()
    if dup:
        raise BusinessError(f"You already have an open {product.code} application (#{dup.id})")
    docs, pending, bank_emi = _context(db, user.id)
    ev = evaluate(profile, product, data.amount, data.tenure_months, data.asset_value, docs,
                  bank_emi=bank_emi, pending_docs=pending)
    app = LoanApplication(user_id=user.id, product_id=product.id, amount=data.amount,
                          tenure_months=data.tenure_months, purpose=data.purpose,
                          asset_value=data.asset_value, docs=",".join(docs),
                          rate=ev["rate"], emi=ev["emi"], foir=ev["foir"],
                          system_score=ev["score"], system_recommendation=ev["recommendation"],
                          checks_json=json.dumps(ev["checks"]))
    db.add(app)
    db.flush()
    audit(db, user.id, "APPLICATION_SUBMITTED", "application", app.id,
          f"{product.code} {data.amount:,.0f} -> {ev['recommendation']}")
    notify(db, user.id, f"Application #{app.id} submitted",
           f"Your {product.name} request for Rs {data.amount:,.0f} was sent to the bank. "
           f"Pre-check result: {ev['recommendation']}.", "APPLICATION")
    notify_role(db, OFFICER, f"New {product.code} application #{app.id}",
                f"{user.full_name} requested Rs {data.amount:,.0f}. System suggests {ev['recommendation']} "
                f"(score {ev['score']}).", "APPLICATION")
    db.commit()
    return app


def resubmit(db, user, app):
    """Customer finished uploading what the officer asked for: re-run checks on the locker and re-queue."""
    if app.user_id != user.id:
        raise BusinessError("Not your application")
    if app.status not in OPEN_APP_STATUSES:
        raise BusinessError("Application is no longer open")
    revalidate(db, app)
    app.status = "SUBMITTED"
    notify_role(db, OFFICER, f"Application #{app.id} updated",
                f"{user.full_name} resubmitted with updated documents.", "APPLICATION")
    audit(db, user.id, "APPLICATION_RESUBMITTED", "application", app.id, app.docs)
    db.commit()


def revalidate_open(db, user_id):
    """Documents or profile changed: refresh checks on every open application of this customer."""
    for a in db.query(LoanApplication).filter(LoanApplication.user_id == user_id,
                                              LoanApplication.status.in_(OPEN_APP_STATUSES)):
        revalidate(db, a)
        a.ai_summary = None  # stale AI note


def revalidate(db, app):
    docs, pending, bank_emi = _context(db, app.user_id)
    ev = evaluate(app.user.profile, app.product, app.amount, app.tenure_months,
                  app.asset_value, docs, bank_emi=bank_emi, pending_docs=pending)
    app.docs = ",".join(docs)
    app.rate, app.emi, app.foir = ev["rate"], ev["emi"], ev["foir"]
    app.system_score, app.system_recommendation = ev["score"], ev["recommendation"]
    app.checks_json = json.dumps(ev["checks"])
    return ev


def decide(db, officer, app, decision, note, override):
    db.refresh(app, with_for_update=True)  # two officers must not decide the same application
    if app.status not in OPEN_APP_STATUSES:
        raise BusinessError(f"Application already {app.status}")
    ev = revalidate(db, app)  # re-validate with latest data before any decision
    app.officer_id, app.officer_note, app.decided_at = officer.id, note, utcnow()
    if decision == "approve":
        if any(c["name"] == "Document verification" and not c["passed"] for c in ev["checks"]):
            raise BusinessError("Required documents must be verified before approval")
        if ev["recommendation"] in ("REJECT", "NEED_DOCS") and not (override and len(note) >= 10):
            raise BusinessError(f"System recommends {ev['recommendation']}. To approve anyway tick "
                                "override and write a justification note (min 10 chars).")
        app.status = "APPROVED"
        loan = activate_loan(db, app)
        notify(db, app.user_id, f"Loan #{loan.id} approved & disbursed",
               f"Rs {app.amount:,.0f} credited. EMI Rs {loan.emi:,.2f} for {app.tenure_months} months. "
               "Enable auto-pay from the Dashboard.", "LOAN")
    elif decision == "reject":
        if len(note) < 5:
            raise BusinessError("A rejection reason is required")
        app.status = "REJECTED"
        notify(db, app.user_id, f"Application #{app.id} rejected", note, "APPLICATION")
    else:
        if len(note) < 5:
            raise BusinessError("Tell the customer what is needed")
        app.status = "NEED_INFO"
        app.decided_at = None
        notify(db, app.user_id, f"More information needed for #{app.id}", note, "APPLICATION")
    audit(db, officer.id, f"APPLICATION_{app.status}", "application", app.id, note)
    db.commit()
    return app


def activate_loan(db, app, first_due=None):
    acct = db.query(BankAccount).filter_by(user_id=app.user_id).first()
    loan = Loan(application_id=app.id, user_id=app.user_id, product_id=app.product_id,
                account_id=acct.id, principal=app.amount, rate=app.rate,
                tenure_months=app.tenure_months, emi=app.emi, outstanding=app.amount,
                disbursed_on=date.today())
    db.add(loan)
    db.flush()
    rows = build_schedule(app.amount, app.rate, app.tenure_months, first_due or add_months(date.today(), 1))
    for r in rows:
        db.add(Installment(loan_id=loan.id, **r))
    loan.emi = rows[0]["emi_amount"]
    acct.balance = round(acct.balance + app.amount, 2)
    db.add(Payment(loan_id=loan.id, amount=app.amount, mode="DISBURSAL", status="SUCCESS"))
    db.flush()
    return loan


def set_autopay(db, loan, enable, actor_id):
    if loan.status != "ACTIVE":
        raise BusinessError("Loan is closed")
    if enable:
        acct = loan.account
        if acct.is_frozen or not acct.netbanking_enabled:
            inst = next_unpaid(loan)
            code = "ACCOUNT_FROZEN" if acct.is_frozen else "NETBANKING_DISABLED"
            from .autopay import explain
            d = explain(code, loan, inst, acct)
            raise BusinessError(d["message"] + " Steps: " + " | ".join(d["steps"]))
        loan.autopay_enabled, loan.mandate_status = True, "ACTIVE"
        loan.mandate_limit = round(loan.emi * 1.25, 2)
    else:
        loan.autopay_enabled, loan.mandate_status, loan.mandate_limit = False, "NONE", 0
    audit(db, actor_id, "AUTOPAY_ON" if enable else "AUTOPAY_OFF", "loan", loan.id)
    db.commit()
    return loan


def manual_pay(db, loan, actor_id):
    inst = next_unpaid(loan)
    if loan.status != "ACTIVE" or not inst:
        raise BusinessError("Nothing to pay")
    db.refresh(inst, with_for_update=True)
    if inst.status in DONE:
        raise BusinessError("Installment has already been paid")
    acct = loan.account
    db.refresh(acct, with_for_update=True)
    if acct.is_frozen:
        raise BusinessError("Account is frozen - visit your branch")
    if acct.balance < inst.emi_amount:
        raise BusinessError(f"Balance Rs {acct.balance:,.2f} is below EMI Rs {inst.emi_amount:,.2f}")
    settle(db, loan, inst, "MANUAL")
    audit(db, actor_id, "MANUAL_PAYMENT", "loan", loan.id, f"installment {inst.number}")
    db.commit()
    return inst


def foreclose(db, loan, actor_id):
    """Pay off the whole outstanding principal now. (Individual floating-rate loans carry no
    foreclosure charge in India; interest accrued within the current month is not modelled here.)"""
    if loan.status != "ACTIVE":
        raise BusinessError("Loan is already closed")
    acct = loan.account
    if acct.is_frozen:
        raise BusinessError("Account is frozen - visit your branch")
    amount = round(loan.outstanding, 2)
    if acct.balance < amount:
        raise BusinessError(f"Foreclosure needs Rs {amount:,.2f}; balance is Rs {acct.balance:,.2f}")
    acct.balance = round(acct.balance - amount, 2)
    for i in loan.installments:
        if i.status not in DONE:
            i.status = "CLOSED_EARLY"
    db.add(Payment(loan_id=loan.id, amount=amount, mode="FORECLOSURE", status="SUCCESS"))
    loan.status, loan.outstanding = "CLOSED", 0.0
    loan.autopay_enabled, loan.mandate_status, loan.mandate_limit = False, "NONE", 0
    audit(db, actor_id, "LOAN_FORECLOSED", "loan", loan.id, f"Rs {amount:,.2f}")
    notify(db, loan.user_id, f"Loan #{loan.id} closed",
           f"Rs {amount:,.2f} paid. Your loan is fully closed; a no-dues certificate follows.", "LOAN")
    db.commit()
    return amount
