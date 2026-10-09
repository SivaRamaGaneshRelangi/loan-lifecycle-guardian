
import json
from pathlib import Path

from fastapi import APIRouter, HTTPException

router = APIRouter(tags=["Ledger"])
DATA_DIR = Path(__file__).resolve().parents[1] / "data"


def load_ledger():
    with (DATA_DIR / "ledger.json").open("r", encoding="utf-8") as file:
        return json.load(file)


@router.get("/ledger")
def get_all_ledger_entries():
    return load_ledger()


@router.get("/ledger/{entry_id}")
def get_ledger_entry(entry_id: str):
    entries = load_ledger()
    entry = next(
        (item for item in entries if item["entry_id"] == entry_id),
        None,
    )

    if entry is None:
        raise HTTPException(status_code=404, detail="Ledger entry not found")

    return entry