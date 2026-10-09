
from pathlib import Path

from fastapi import APIRouter, HTTPException

router = APIRouter(tags=["Policies"])

POLICY_DIR = Path(__file__).resolve().parents[2] / "policies"

ALLOWED_POLICIES = {
    "emi_failure.md",
    "onboarding.md",
    "loan_closure.md",
}


@router.get("/policies")
def get_policy_list():
    return {"policies": sorted(ALLOWED_POLICIES)}


@router.get("/policies/{policy_name}")
def get_policy(policy_name: str):
    if policy_name not in ALLOWED_POLICIES:
        raise HTTPException(status_code=404, detail="Policy not found")

    policy_path = POLICY_DIR / policy_name

    if not policy_path.is_file():
        raise HTTPException(
            status_code=404,
            detail=f"Policy file {policy_name} has not been created yet",
        )

    return {
        "policy_name": policy_name,
        "content": policy_path.read_text(encoding="utf-8"),
    }