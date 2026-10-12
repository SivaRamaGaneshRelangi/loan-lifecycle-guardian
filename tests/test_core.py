from datetime import date

from tests.conftest import login
from app.services.emi import build_schedule, calc_emi


def test_emi_and_schedule():
    assert abs(calc_emi(100000, 12, 12) - 8884.88) < 0.01
    rows = build_schedule(100000, 12, 12, date(2026, 1, 5))
    assert len(rows) == 12
    assert abs(sum(r["principal_part"] for r in rows) - 100000) < 0.01


def test_rbac(client):
    cust = login(client, "rahul", "Cust@1234")
    assert client.get("/api/officer/applications", headers=cust).status_code == 403
    assert client.get("/api/admin/users", headers=cust).status_code == 403
    assert client.get("/api/me/loans").status_code == 401
    off = login(client, "officer1", "Officer@123")
    assert client.get("/api/officer/applications", headers=off).status_code == 200
    assert client.get("/api/me/loans", headers=off).status_code == 403


def test_register_validation(client):
    bad = {"username": "newuser1", "password": "short", "full_name": "N U", "email": "x@y.com",
           "dob": "1990-01-01", "pan": "BADPAN", "monthly_income": 50000, "employment_type": "SALARIED"}
    assert client.post("/api/auth/register", json=bad).status_code == 422


def test_officer_queue_recommendations(client):
    off = login(client, "officer1", "Officer@123")
    rows = client.get("/api/officer/applications", headers=off).json()
    recs = {r["customer"]["name"]: r["system_recommendation"] for r in rows}
    assert recs["Anita Verma"] == "APPROVE"
    assert recs["Vikram Singh"] == "REJECT"


def test_reject_needs_override_then_approve(client):
    off = login(client, "officer1", "Officer@123")
    rows = client.get("/api/officer/applications", headers=off).json()
    vik = next(r for r in rows if r["customer"]["name"] == "Vikram Singh")
    r = client.post(f"/api/officer/applications/{vik['id']}/decision", headers=off,
                    json={"decision": "approve", "note": ""})
    assert r.status_code == 400
    ani = next(r for r in rows if r["customer"]["name"] == "Anita Verma")
    r = client.post(f"/api/officer/applications/{ani['id']}/decision", headers=off,
                    json={"decision": "approve", "note": "Looks good"})
    assert r.status_code == 200 and r.json()["status"] == "APPROVED"


def test_autopay_engine_reasons(client):
    admin = login(client, "admin", "Admin@123")
    res = client.post("/api/admin/run-autopay", headers=admin, json={}).json()["results"]
    by = {r["customer"]: (r["result"], r["code"]) for r in res}
    assert by["Rahul Sharma"] == ("FAILED", "INSUFFICIENT_BALANCE")
    assert by["Priya Reddy"] == ("FAILED", "NETBANKING_DISABLED")
    assert by["Suresh Kumar"] == ("PAID", None)
    cust = login(client, "priya", "Cust@1234")
    loans = client.get("/api/me/loans", headers=cust).json()
    d = client.get(f"/api/me/loans/{loans[0]['id']}/autopay-status", headers=cust).json()
    assert d["code"] == "NETBANKING_DISABLED" and "Home Loan" in d["netbanking_path"]


def test_agent_fallback_and_isolation(client):
    cust = login(client, "rahul", "Cust@1234")
    r = client.post("/api/agent/chat", headers=cust, json={"message": "why did my autopay fail?"}).json()
    assert r["mode"] == "rules" and "Rs" in r["reply"]
    assert "Priya" not in r["reply"]
