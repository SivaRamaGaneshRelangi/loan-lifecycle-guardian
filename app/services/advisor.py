"""Loan-fit advisor: which product is the bank most likely to approve for THIS customer right now?

The ranking is a transparent rule-based estimate built from the same checks the officer queue uses
(credit margin, free cash-flow after all existing EMIs incl. our own loans, KYC, documents).
The LLM only narrates the result - it never changes it. It is an estimate, not a promise of approval.
"""
import json
import math
from datetime import date

from ..models import LoanProduct
from . import documents, llm
from .eligibility import adjusted_rate, age_on, bank_obligations, evaluate

BANDS = [(800, "Excellent", None), (750, "Very good", 800), (700, "Good", 750), (650, "Fair", 700),
         (0, "Needs work", 650)]
RATE_STEP = {800: 0.5, 750: 0.75, 700: 0.75}  # pct-point rate improvement on reaching a threshold (650: none)


def credit_tier(score):
    for floor, name, nxt in BANDS:
        if score >= floor:
            gain = RATE_STEP.get(nxt) if nxt else None
            return {"band": name, "score": score, "next_threshold": nxt,
                    "points_needed": (nxt - score) if nxt else 0, "rate_gain": gain}


def _max_principal(emi_cap, rate, n):
    if emi_cap <= 0 or n <= 0:
        return 0.0
    r = rate / 1200.0
    if r == 0:
        return emi_cap * n
    f = (1 + r) ** n
    return emi_cap * (f - 1) / (r * f)


def _floor_to(x, step):
    return math.floor(x / step) * step


def loan_fit(db, user, today=None):
    today = today or date.today()
    pr = user.profile
    bank_emi = bank_obligations(db, user.id)
    docs, pending = documents.received(db, user.id)
    obligations = pr.existing_emi + bank_emi
    age = age_on(pr.dob, today)
    out = []
    for p in db.query(LoanProduct).filter_by(active=True):
        required = [d for d in p.required_docs.split(",") if d]
        rate = adjusted_rate(p.base_rate, pr.credit_score)
        n = min(p.max_tenure, int((p.max_age_at_maturity - age) * 12))
        emi_cap = p.max_foir * pr.monthly_income - obligations
        max_amount = min(p.max_amount, _max_principal(emi_cap, rate, n))
        blockers, why, todo = [], [], []
        if age < 21:
            blockers.append("Minimum age for loans is 21")
        if n < p.min_tenure:
            blockers.append("Age limit at maturity leaves too short a tenure for this product")
        if pr.credit_score < p.min_credit_score:
            blockers.append(f"Credit score {pr.credit_score} is {p.min_credit_score - pr.credit_score} points "
                            f"below the {p.min_credit_score} needed")
        if pr.monthly_income < p.min_income:
            blockers.append(f"Income Rs {pr.monthly_income:,.0f} is below the Rs {p.min_income:,.0f} minimum")
        if max_amount < p.min_amount:
            blockers.append(f"After your EMIs (Rs {obligations:,.0f}/month) there is room for only "
                            f"Rs {max(0, max_amount):,.0f}, below the Rs {p.min_amount:,.0f} minimum")
        item = {"code": p.code, "name": p.name, "rate": rate, "tenure_months": max(n, 0),
                "max_amount": 0.0, "suggested_amount": 0.0, "emi": 0.0, "ease_score": 0,
                "likelihood": "NOT_ELIGIBLE", "blockers": blockers, "why": why, "todo": todo,
                "asset_needed": None}
        if blockers:
            out.append(item)
            continue
        suggested = max(p.min_amount, _floor_to(0.8 * max_amount, 10000 if max_amount >= 100000 else 1000))
        suggested = min(suggested, _floor_to(max_amount, 1000) or max_amount)
        asset = math.ceil(suggested / p.max_ltv / 1000) * 1000 if p.max_ltv else 0
        ev = evaluate(pr, p, suggested, n, asset, required, today, bank_emi=bank_emi)
        soft = sum(1 for c in ev["checks"] if not c["passed"] and c["severity"] == "soft")
        missing = [d for d in required if d not in docs]
        cm = pr.credit_score - p.min_credit_score
        free = max(0.0, emi_cap) / pr.monthly_income
        ease = 40 + min(25, cm / 4) + min(25, free * 60) - 8 * soft \
            - (0 if pr.kyc_verified else 10) + (10 if not missing else 0) - (10 if p.max_ltv else 0)
        ease = int(max(0, min(100, round(ease))))
        why.append(f"Credit score {pr.credit_score} is {cm} points above the {p.min_credit_score} cut-off")
        why.append(f"Free monthly capacity for a new EMI: Rs {max(0, emi_cap):,.0f} "
                   f"(after Rs {obligations:,.0f} existing EMIs)")
        if soft:
            todo.append("Some margins are thin (see eligibility checks) - a smaller amount improves odds")
        if not pr.kyc_verified:
            todo.append("Complete KYC - an officer must verify it before approval")
        if missing:
            todo.append("Upload: " + ", ".join(documents.DOC_LABELS[d] for d in missing))
        if asset:
            todo.append(f"Declare an asset worth at least Rs {asset:,.0f} (limit {p.max_ltv:.0%} of value)")
        item.update(max_amount=round(_floor_to(max_amount, 1000), 2), suggested_amount=suggested, emi=ev["emi"],
                    ease_score=ease, asset_needed=asset or None,
                    likelihood="HIGH" if ease >= 75 else "MEDIUM" if ease >= 55 else "LOW")
        out.append(item)
    out.sort(key=lambda x: (-x["ease_score"], x["name"]))
    return {"options": out, "tier": credit_tier(pr.credit_score), "obligations": {
        "other_lenders": pr.existing_emi, "our_active_loans": bank_emi, "total": obligations,
        "income": pr.monthly_income, "ratio": round(obligations / pr.monthly_income, 4)},
        "tips": score_tips(pr, obligations, docs)}


def score_tips(pr, obligations, docs):
    tips, t = [], credit_tier(pr.credit_score)
    if t["next_threshold"]:
        gain = (f", which lowers your rate by about {t['rate_gain']} percentage points" if t["rate_gain"]
                else ", the band most lenders prefer")
        tips.append(f"You are {t['points_needed']} points from {t['next_threshold']}{gain}. "
                    "Pay every EMI on time and keep card usage under 30%.")
    ratio = obligations / pr.monthly_income if pr.monthly_income else 1
    if ratio > 0.35:
        tips.append(f"EMIs take {ratio:.0%} of your income. Closing or prepaying your smallest loan frees capacity "
                    "for a bigger approval.")
    if not pr.kyc_verified:
        tips.append("KYC is pending - verified KYC removes the most common cause of delays.")
    if not docs:
        tips.append("Upload your documents once in the Documents tab; they are reused for every application.")
    tips.append("Turn on auto-pay for existing loans so a low balance never causes a missed EMI.")
    return tips


def narrate(result, user):
    """Plain-language summary. LLM if available, deterministic text otherwise."""
    opts = [o for o in result["options"] if o["likelihood"] != "NOT_ELIGIBLE"]
    if opts:
        b = opts[0]
        fallback = (f"Your best fit right now is the {b['name']}: up to Rs {b['max_amount']:,.0f} at about "
                    f"{b['rate']}% (EMI near Rs {b['emi']:,.0f} for a Rs {b['suggested_amount']:,.0f} request). "
                    f"Likelihood: {b['likelihood']}. ")
        if len(opts) > 1:
            fallback += "Next best: " + ", ".join(o["name"] for o in opts[1:3]) + ". "
    else:
        fallback = "No product is a comfortable fit right now. Focus on the improvement tips below. "
    data = {"tier": result["tier"], "obligations": result["obligations"],
            "options": [{k: o[k] for k in ("name", "likelihood", "ease_score", "max_amount", "rate", "blockers", "todo")}
                        for o in result["options"]], "tips": result["tips"]}
    text = llm.generate(
        "Write a friendly 80-word summary for a bank customer about which loan they are most likely to get "
        "approved for, and one action to improve their chances. Use only the data; do not promise approval. "
        "Amounts in Rs.\nDATA: " + json.dumps(data),
        system="You are a careful retail-banking advisor.")
    return (text, "llm") if text else (fallback.strip(), "rules")
