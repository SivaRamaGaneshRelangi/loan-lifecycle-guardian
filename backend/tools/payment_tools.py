
import json
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[1] / "data"


def _load(filename):
    with (DATA_DIR / filename).open("r", encoding="utf-8") as file:
        return json.load(file)


def list_payments():
    return _load("payments.json")


def get_payment(payment_id: str):
    return next(
        (item for item in list_payments()
         if item["payment_id"] == payment_id),
        None,
    )


def get_payments_for_loan(loan_id: str):
    return [
        item for item in list_payments()
        if item["loan_id"] == loan_id
    ]


def list_emis():
    return _load("emis.json")


def get_emis_for_loan(loan_id: str):
    return [
        item for item in list_emis()
        if item["loan_id"] == loan_id
    ]