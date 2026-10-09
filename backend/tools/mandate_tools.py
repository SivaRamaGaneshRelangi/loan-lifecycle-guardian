
import json
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[1] / "data"


def list_mandates():
    with (DATA_DIR / "mandates.json").open("r", encoding="utf-8") as file:
        return json.load(file)


def get_mandate(mandate_id: str):
    return next(
        (item for item in list_mandates()
         if item["mandate_id"] == mandate_id),
        None,
    )


def get_mandate_for_loan(loan_id: str):
    return next(
        (item for item in list_mandates()
         if item["loan_id"] == loan_id),
        None,
    )


def is_mandate_active(loan_id: str) -> bool:
    mandate = get_mandate_for_loan(loan_id)
    return mandate is not None and mandate["status"] == "ACTIVE"