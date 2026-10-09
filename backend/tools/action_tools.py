
from datetime import datetime, timezone


def propose_action(
    action_type: str,
    loan_id: str,
    reason: str,
    requires_approval: bool = True,
):
    return {
        "action_id": None,
        "loan_id": loan_id,
        "action_type": action_type,
        "reason": reason,
        "status": "PROPOSED",
        "requires_approval": requires_approval,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "executed": False,
        "message": "Proposal only. No bank data was changed.",
    }


def propose_mandate_reactivation(loan_id: str):
    return propose_action(
        action_type="REACTIVATE_MANDATE",
        loan_id=loan_id,
        reason="Mandate reactivation requires an approved process.",
        requires_approval=True,
    )


def propose_emi_retry(loan_id: str):
    return propose_action(
        action_type="RETRY_EMI",
        loan_id=loan_id,
        reason="Payment retry must be permitted by policy and explicitly approved.",
        requires_approval=True,
    )


def propose_loan_closure(loan_id: str):
    return propose_action(
        action_type="CLOSE_LOAN",
        loan_id=loan_id,
        reason="Loan closure requires outstanding-balance and collateral checks.",
        requires_approval=True,
    )