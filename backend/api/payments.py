
import json
from pathlib import Path

from fastapi import APIRouter, HTTPException

router = APIRouter(tags=["Payments"])
DATA_DIR = Path(__file__).resolve().parents[1] / "data"


def load_payments():
    with (DATA_DIR / "payments.json").open("r", encoding="utf-8") as file:
        return json.load(file)


@router.get("/payments")
def get_all_payments():
    return load_payments()


@router.get("/payments/{payment_id}")
def get_payment(payment_id: str):
    payments = load_payments()
    payment = next(
        (item for item in payments if item["payment_id"] == payment_id),
        None,
    )

    if payment is None:
        raise HTTPException(status_code=404, detail="Payment not found")

    return payment