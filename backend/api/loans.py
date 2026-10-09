
from pathlib import Path

import json
from fastapi import APIRouter, HTTPException

router = APIRouter(tags=["Loans"])

DATA_DIR = Path(__file__).resolve().parents[1] / "data"


def load_loans():
    with (DATA_DIR / "loans.json").open("r", encoding="utf-8") as file:
        return json.load(file)


@router.get("/loans")
def get_all_loans():
    return load_loans()


@router.get("/loans/{loan_id}")
def get_loan(loan_id: str):
    loans = load_loans()
    loan = next((item for item in loans if item["loan_id"] == loan_id), None)

    if loan is None:
        raise HTTPException(status_code=404, detail="Loan not found")

    return loan