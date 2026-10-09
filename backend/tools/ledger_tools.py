
import json
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[1] / "data"


def list_ledger_entries():
    with (DATA_DIR / "ledger.json").open("r", encoding="utf-8") as file:
        return json.load(file)


def get_ledger_entry(entry_id: str):
    return next(
        (item for item in list_ledger_entries()
         if item["entry_id"] == entry_id),
        None,
    )


def get_ledger_for_loan(loan_id: str):
    return [
        item for item in list_ledger_entries()
        if item["loan_id"] == loan_id
    ]


def has_active_collateral_lien(loan_id: str) -> bool:
    return any(
        item.get("collateral_status") == "LIEN_ACTIVE"
        for item in get_ledger_for_loan(loan_id)
    )