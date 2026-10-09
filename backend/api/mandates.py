
import json
from pathlib import Path

from fastapi import APIRouter, HTTPException

router = APIRouter(tags=["Mandates"])
DATA_DIR = Path(__file__).resolve().parents[1] / "data"


def load_mandates():
    with (DATA_DIR / "mandates.json").open("r", encoding="utf-8") as file:
        return json.load(file)


@router.get("/mandates")
def get_all_mandates():
    return load_mandates()


@router.get("/mandates/{mandate_id}")
def get_mandate(mandate_id: str):
    mandates = load_mandates()
    mandate = next(
        (item for item in mandates if item["mandate_id"] == mandate_id),
        None,
    )

    if mandate is None:
        raise HTTPException(status_code=404, detail="Mandate not found")

    return mandate