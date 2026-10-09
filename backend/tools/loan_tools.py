
import json
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[1] / "data"


def _load(filename):
    with (DATA_DIR / filename).open("r", encoding="utf-8") as file:
        return json.load(file)


def list_loans():
    return _load("loans.json")


def get_loan(loan_id: str):
    return next(
        (loan for loan in list_loans() if loan["loan_id"] == loan_id),
        None,
    )


def get_customer(customer_id: str):
    customers = _load("customers.json")
    return next(
        (customer for customer in customers
         if customer["customer_id"] == customer_id),
        None,
    )


def get_customer_for_loan(loan_id: str):
    loan = get_loan(loan_id)
    if loan is None:
        return None
    return get_customer(loan["customer_id"])