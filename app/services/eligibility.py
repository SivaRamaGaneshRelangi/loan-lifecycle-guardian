"""Deterministic loan validation / readiness engine. The LLM never decides - it only explains."""
from datetime import date

from .emi import calc_emi


def age_on(dob: date, d: date) -> int:
    return d.year - dob.year - ((d.month, d.day) < (dob.month, dob.day))


def bureau_score(pan: str) -> int:
    """Simulated credit bureau: stable pseudo-score 600-849 derived from PAN."""
    return 600 + (sum(ord(c) * (i + 3) for i, c in enumerate(pan)) % 250)


def adjusted_rate(base: float, score: int) -> float:
    if score >= 800:
        return round(base - 0.5, 2)
    if score >= 750:
        return round(base, 2)
    if score >= 700:
        return round(base + 0.75, 2)
    return round(base + 1.5, 2)


def bank_obligations(db, user_id) -> float:
    """Sum of EMIs of this customer's ACTIVE loans at this bank (never self-reported)."""
    from ..models import Loan
    return round(sum(l.emi for l in db.query(Loan).filter_by(user_id=user_id, status="ACTIVE")), 2)


def evaluate(profile, product, amount, tenure, asset_value, docs, today=None, bank_emi=0.0, pending_docs=()):
    """bank_emi: EMIs of active loans at THIS bank. profile.existing_emi: EMIs with OTHER lenders."""
    today = today or date.today()
    checks = []

    def add(name, ok, detail, severity="hard"):
        checks.append({"name": name, "passed": bool(ok), "detail": detail, "severity": severity})

    rate = adjusted_rate(product.base_rate, profile.credit_score)
    emi = calc_emi(amount, rate, tenure) if amount > 0 and tenure > 0 else 0.0
    other_emi = profile.existing_emi + bank_emi
    foir = (other_emi + emi) / profile.monthly_income if profile.monthly_income else 9.9

    add("Amount range", product.min_amount <= amount <= product.max_amount,
        f"Allowed {product.min_amount:,.0f} - {product.max_amount:,.0f}; requested {amount:,.0f}")
    add("Tenure range", product.min_tenure <= tenure <= product.max_tenure,
        f"Allowed {product.min_tenure}-{product.max_tenure} months; requested {tenure}")
    age = age_on(profile.dob, today)
    end_age = age + tenure / 12
    add("Age eligibility", age >= 21 and end_age <= product.max_age_at_maturity,
        f"Age {age} (minimum 21), age at maturity {end_age:.1f} (max {product.max_age_at_maturity})")
    add("Minimum income", profile.monthly_income >= product.min_income,
        f"Income {profile.monthly_income:,.0f} vs required {product.min_income:,.0f}")
    ok_cs = profile.credit_score >= product.min_credit_score
    add("Credit score", ok_cs, f"Score {profile.credit_score} vs minimum {product.min_credit_score}")
    if ok_cs and profile.credit_score < product.min_credit_score + 30:
        add("Credit score margin", False, "Score is within 30 points of the cut-off", "soft")
    ok_foir = foir <= product.max_foir
    add("Repayment capacity (FOIR)", ok_foir,
        f"Obligations/income = {foir:.0%} (limit {product.max_foir:.0%}) = other lenders {profile.existing_emi:,.0f}"
        f" + our active loans {bank_emi:,.0f} + new EMI {emi:,.0f} @ {rate}%")
    if ok_foir and foir > product.max_foir - 0.05:
        add("FOIR margin", False, "Debt burden is within 5 points of the limit", "soft")
    if product.max_ltv:
        if asset_value <= 0:
            add("Asset value declared", False, "Asset value is required for this product")
        else:
            ltv = amount / asset_value
            add("Loan-to-value", ltv <= product.max_ltv,
                f"LTV {ltv:.0%} (limit {product.max_ltv:.0%})")
    add("KYC verified", profile.kyc_verified,
        "KYC verified" if profile.kyc_verified else "KYC pending - officer must verify", "docs")
    required = [d for d in product.required_docs.split(",") if d]
    missing = [d for d in required if d not in docs]
    add("Documents", not missing, "All documents received" if not missing
        else f"Missing: {', '.join(missing)}", "docs")
    waiting = [d for d in required if d in pending_docs]
    if not missing and waiting:
        add("Document verification", False, f"Awaiting officer verification: {', '.join(waiting)}", "soft")

    hard = sum(1 for c in checks if not c["passed"] and c["severity"] == "hard")
    docs_f = sum(1 for c in checks if not c["passed"] and c["severity"] == "docs")
    soft = sum(1 for c in checks if not c["passed"] and c["severity"] == "soft")
    score = max(0, 100 - 30 * hard - 10 * docs_f - 8 * soft)
    if hard:
        rec = "REJECT"
    elif docs_f:
        rec = "NEED_DOCS"
    elif soft or score < 80:
        rec = "REVIEW"
    else:
        rec = "APPROVE"
    return {"rate": rate, "emi": emi, "foir": round(foir, 4), "score": score,
            "recommendation": rec, "checks": checks,
            "obligations": {"other_lenders": profile.existing_emi, "our_active_loans": bank_emi,
                            "new_emi": emi, "income": profile.monthly_income}}
