
import json
from pathlib import Path
from uuid import uuid4
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/agent", tags=["AI Agent Demo"])

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
POLICY_DIR = Path(__file__).resolve().parents[2] / "policies"

# Temporary demo storage. Requests disappear when the server restarts.
APPROVALS = {}
AUDIT_LOG = []


def read_json(filename):
    with (DATA_DIR / filename).open("r", encoding="utf-8") as file:
        return json.load(file)


def find_record(filename, key, value):
    return next(
        (row for row in read_json(filename) if row.get(key) == value),
        None,
    )


def read_policy(filename):
    path = POLICY_DIR / filename
    if path.exists():
        return path.read_text(encoding="utf-8")
    return "Policy file not found."


def record_audit(event, details):
    AUDIT_LOG.append({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": event,
        "details": details,
    })


@router.post("/investigate/{loan_id}")
def investigate_loan(loan_id: str):
    loan = find_record("loans.json", "loan_id", loan_id)
    if not loan:
        raise HTTPException(status_code=404, detail="Loan not found")

    customer = find_record(
        "customers.json", "customer_id", loan["customer_id"]
    )

    emis = [
        x for x in read_json("emis.json")
        if x.get("loan_id") == loan_id
    ]
    payments = [
        x for x in read_json("payments.json")
        if x.get("loan_id") == loan_id
    ]
    mandate = find_record("mandates.json", "loan_id", loan_id)
    ledger = [
        x for x in read_json("ledger.json")
        if x.get("loan_id") == loan_id
    ]

    scenario = loan.get("scenario", "")
    if scenario == "EMI_FAILURE":
        policy_name = "emi_failure.md"
        issue = "EMI failure detected; inspect payment and mandate."
        action = "REACTIVATE_MANDATE"
        reason = (
            "The payment failed and the mandate is inactive. "
            "An approved mandate reactivation process is required."
        )
        blocked = not mandate or mandate.get("status") != "INACTIVE"

    elif scenario == "MISSING_DOCUMENTS":
        policy_name = "onboarding.md"
        issue = "Onboarding verification is incomplete."
        action = "REQUEST_MISSING_DOCUMENTS"
        reason = (
            "Customer KYC or onboarding requirements need review "
            "before loan approval."
        )
        blocked = False

    elif scenario == "COLLATERAL_BLOCK":
        policy_name = "loan_closure.md"
        issue = "Loan closure is blocked by a collateral lien."
        action = "RELEASE_COLLATERAL_LIEN"
        reason = (
            "The ledger indicates an active collateral lien. "
            "Resolve and verify the lien before loan closure."
        )
        blocked = any(
            x.get("collateral_status") == "LIEN_ACTIVE"
            for x in ledger
        )

    else:
        policy_name = "emi_failure.md"
        issue = "Routine loan review completed."
        action = "NO_ACTION"
        reason = "No special scenario was identified."
        blocked = False

    policy = read_policy(policy_name)
    request_id = "APR-" + uuid4().hex[:8].upper()

    approval = {
        "request_id": request_id,
        "loan_id": loan_id,
        "customer": customer,
        "loan": loan,
        "emi_records": emis,
        "payment_records": payments,
        "mandate": mandate,
        "ledger_records": ledger,
        "policy_name": policy_name,
        "policy_text": policy,
        "issue": issue,
        "proposed_action": action,
        "reason": reason,
        "guardrail_status": (
            "BLOCKED_PENDING_REMEDIATION" if blocked else "REQUIRES_HUMAN_APPROVAL"
        ),
        "approval_status": "PENDING",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    APPROVALS[request_id] = approval
    record_audit("INVESTIGATION_COMPLETED", {
        "request_id": request_id,
        "loan_id": loan_id,
        "issue": issue,
        "proposed_action": action,
    })

    return approval


@router.get("/approvals")
def list_approvals():
    return list(APPROVALS.values())


class ApprovalDecision(BaseModel):
    decision: str
    reviewer: str = "Demo Reviewer"
    comment: str = ""


@router.post("/approvals/{request_id}/decision")
def decide_approval(request_id: str, body: ApprovalDecision):
    approval = APPROVALS.get(request_id)
    if not approval:
        raise HTTPException(status_code=404, detail="Approval request not found")

    decision = body.decision.strip().upper()
    if decision not in {"APPROVE", "REJECT"}:
        raise HTTPException(
            status_code=400,
            detail="decision must be APPROVE or REJECT",
        )

    if approval["approval_status"] != "PENDING":
        raise HTTPException(
            status_code=409,
            detail="This request has already been reviewed",
        )

    if decision == "APPROVE" and approval["guardrail_status"] == "BLOCKED_PENDING_REMEDIATION":
        raise HTTPException(
            status_code=403,
            detail="Guardrail blocked this action. Resolve the blocker first.",
        )

    approval["approval_status"] = (
        "APPROVED" if decision == "APPROVE" else "REJECTED"
    )
    approval["reviewer"] = body.reviewer
    approval["review_comment"] = body.comment
    approval["reviewed_at"] = datetime.now(timezone.utc).isoformat()

    record_audit("HUMAN_REVIEW_RECORDED", {
        "request_id": request_id,
        "decision": decision,
        "reviewer": body.reviewer,
        "comment": body.comment,
    })

    return {
        "message": "Human decision recorded. No real bank action was executed.",
        "approval": approval,
    }


@router.get("/audit")
def get_audit_log():
    return AUDIT_LOG