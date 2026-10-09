
from pathlib import Path

POLICY_DIR = Path(__file__).resolve().parents[2] / "policies"

ALLOWED_POLICIES = {
    "emi_failure.md",
    "onboarding.md",
    "loan_closure.md",
}


def list_policies():
    return sorted(ALLOWED_POLICIES)


def get_policy(policy_name: str):
    if policy_name not in ALLOWED_POLICIES:
        return None

    path = POLICY_DIR / policy_name
    if not path.is_file():
        return None

    return path.read_text(encoding="utf-8")


def get_emi_failure_policy():
    return get_policy("emi_failure.md")


def get_onboarding_policy():
    return get_policy("onboarding.md")


def get_loan_closure_policy():
    return get_policy("loan_closure.md")