import json
from pathlib import Path

from fastapi import FastAPI, HTTPException

from backend.agent.graph import router as agent_router
from backend.api.loans import router as loans_router
from backend.api.payments import router as payments_router
from backend.api.mandates import router as mandates_router
from backend.api.ledger import router as ledger_router
from backend.api.policies import router as policies_router

app = FastAPI(
    title="Loan Lifecycle Guardian",
    description="Simulated bank APIs for an agentic loan lifecycle prototype",
    version="0.3.0",
)

DATA_DIR = Path(__file__).resolve().parent / "data"


def load_customers():
    with (DATA_DIR / "customers.json").open("r", encoding="utf-8") as file:
        return json.load(file)


@app.get("/")
def home():
    return {
        "message": "Loan Lifecycle Guardian API is running",
        "status": "healthy",
    }


@app.get("/customers", tags=["Customers"])
def get_all_customers():
    return load_customers()


@app.get("/customers/{customer_id}", tags=["Customers"])
def get_customer(customer_id: str):
    customers = load_customers()
    customer = next(
        (item for item in customers if item["customer_id"] == customer_id),
        None,
    )

    if customer is None:
        raise HTTPException(status_code=404, detail="Customer not found")

    return customer


app.include_router(loans_router)
app.include_router(payments_router)
app.include_router(mandates_router)
app.include_router(ledger_router)
app.include_router(policies_router)
app.include_router(agent_router)