"""Proactive 'guardian' alerts for a customer: what needs attention, with one-click actions."""
import math
from datetime import date

from ..config import settings
from ..models import Loan, LoanApplication
from .autopay import diagnose, next_unpaid

RANK = {"high": 0, "medium": 1, "low": 2, "info": 3}


def customer_insights(db, user, today=None):
    today = today or date.today()
    demo = settings.DEMO_MODE
    items = []

    def add(sev, title, msg, actions=None, loan_id=None):
        items.append({"severity": sev, "title": title, "message": msg,
                      "actions": actions or [], "loan_id": loan_id})

    for l in db.query(Loan).filter_by(user_id=user.id, status="ACTIVE").all():
        inst = next_unpaid(l)
        if not inst:
            continue
        acct, tag = l.account, f"{l.product.name} #{l.id}"
        days = (inst.due_date - today).days
        diag = diagnose(l, inst, acct)
        pay = {"type": "pay_now", "label": "Pay now", "loan_id": l.id}
        enable = {"type": "enable_autopay", "label": "Enable auto-pay", "loan_id": l.id}
        if inst.status in ("FAILED", "OVERDUE") or days < 0:
            why = f" Reason: {diag['message']}" if diag else ""
            add("high", f"{tag}: EMI #{inst.number} overdue",
                f"Rs {inst.emi_amount:,.2f} was due on {inst.due_date}.{why}", [pay], l.id)
            if diag and demo and diag["code"] == "INSUFFICIENT_BALANCE":
                items[-1]["actions"].insert(0, {"type": "add_funds", "label": f"Add Rs {math.ceil(diag['shortfall'])} (demo)",
                                                "balance_to": math.ceil(acct.balance + diag["shortfall"])})
            continue
        if days <= 7:
            if not l.autopay_enabled:
                add("medium", f"{tag}: auto-pay is OFF",
                    f"EMI Rs {inst.emi_amount:,.2f} is due in {days} day(s) on {inst.due_date}.", [enable, pay], l.id)
            elif diag:
                acts = []
                if diag["code"] == "INSUFFICIENT_BALANCE" and demo:
                    acts.append({"type": "add_funds", "label": f"Add Rs {math.ceil(diag['shortfall'])} (demo)",
                                 "balance_to": math.ceil(acct.balance + diag["shortfall"])})
                if diag["code"] == "NETBANKING_DISABLED" and demo:
                    acts.append({"type": "enable_netbanking", "label": "Enable net banking (demo)"})
                if diag["code"] == "MANDATE_LIMIT_EXCEEDED":
                    acts.append({**enable, "label": "Reset mandate limit"})
                add("high", f"{tag}: auto-debit on {inst.due_date} will FAIL",
                    diag["message"] + " " + (diag["steps"][0] if diag["steps"] else ""), acts, l.id)
            else:
                add("info", f"{tag}: EMI due in {days} day(s)",
                    f"Rs {inst.emi_amount:,.2f} will be auto-debited from XXXX{acct.account_no[-4:]}. All set.", [], l.id)
        elif not l.autopay_enabled:
            add("low", f"{tag}: auto-pay is OFF", "Turn it on so EMIs are never missed.", [enable], l.id)
    for a in db.query(LoanApplication).filter_by(user_id=user.id, status="NEED_INFO").all():
        add("high", f"Application #{a.id}: bank needs more information",
            a.officer_note or "Please resubmit documents.", [{"type": "goto", "label": "Open applications", "tab": "Applications"}])
    if not items:
        add("info", "All good", "No action needed right now.")
    return sorted(items, key=lambda x: RANK[x["severity"]])
