from datetime import date

import pytest

from tests.conftest import login

PERSONAL = {"product_code": "PERSONAL", "amount": 500000, "tenure_months": 36}
ALL3 = ["ID_PROOF", "ADDRESS_PROOF", "INCOME_PROOF"]


def make_customer(client, username, income=60000, score=780, existing_emi=0, kyc=True, docs=ALL3):
    r = client.post("/api/auth/register", json={
        "username": username, "password": "Passw0rd1", "full_name": "Emi Tester", "email": "e@t.com",
        "dob": "1990-01-01", "pan": "ABCDE1234F", "monthly_income": income, "existing_emi": existing_emi,
        "employment_type": "SALARIED"})
    assert r.status_code == 200, r.text
    uid = r.json()["user"]["id"]
    h = {"Authorization": "Bearer " + r.json()["token"]}
    from app.database import SessionLocal
    from app.models import CustomerProfile
    db = SessionLocal()
    p = db.query(CustomerProfile).filter_by(user_id=uid).first()
    p.credit_score, p.kyc_verified = score, kyc
    db.commit()
    db.close()
    for d in docs:
        assert client.post("/api/me/documents/sample", json={"doc_type": d}, headers=h).status_code == 200
    return h, uid


def test_existing_bank_loan_counts_in_foir(client):
    h, uid = make_customer(client, "emitest1")
    before = client.post("/api/me/applications/precheck", json=PERSONAL, headers=h).json()
    assert before["recommendation"] == "APPROVE"
    assert before["obligations"]["our_active_loans"] == 0
    app = client.post("/api/me/applications", json=PERSONAL, headers=h).json()
    off = login(client, "officer1", "Officer@123")
    r = client.post(f"/api/officer/applications/{app['id']}/decision", headers=off,
                    json={"decision": "approve", "note": "ok"})
    assert r.status_code == 200 and r.json()["status"] == "APPROVED"
    loans = client.get("/api/me/loans", headers=h).json()
    assert len(loans) == 1
    after = client.post("/api/me/applications/precheck", json=PERSONAL, headers=h).json()
    assert after["obligations"]["our_active_loans"] == pytest.approx(loans[0]["emi"])
    assert after["foir"] > before["foir"] + 0.2          # first loan's EMI is now part of the burden
    assert "our active loans" in next(c["detail"] for c in after["checks"] if "FOIR" in c["name"])


def test_missing_documents_need_docs(client):
    h, _ = make_customer(client, "nodocs1", docs=[])
    r = client.post("/api/me/applications/precheck", json=PERSONAL, headers=h).json()
    assert r["recommendation"] == "NEED_DOCS"
    assert any(c["name"] == "Documents" and not c["passed"] for c in r["checks"])


def test_document_upload_validation_and_review(client):
    h, uid = make_customer(client, "doctest1", docs=[])
    bad = client.post("/api/me/documents", headers=h, data={"doc_type": "ID_PROOF"},
                      files={"file": ("x.pdf", b"this is not a pdf" * 30, "application/pdf")})
    assert bad.status_code == 400
    txt = client.post("/api/me/documents", headers=h, data={"doc_type": "ID_PROOF"},
                      files={"file": ("x.txt", b"hello" * 100, "text/plain")})
    assert txt.status_code == 400
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 600
    ok = client.post("/api/me/documents", headers=h, data={"doc_type": "ID_PROOF"},
                     files={"file": ("id.png", png, "image/png")})
    assert ok.status_code == 200 and ok.json()["status"] == "UPLOADED"   # image -> manual review
    dup = client.post("/api/me/documents", headers=h, data={"doc_type": "ID_PROOF"},
                      files={"file": ("id.png", png, "image/png")})
    assert dup.status_code == 400
    doc_id = ok.json()["id"]
    # another customer cannot read it
    other = login(client, "rahul", "Cust@1234")
    assert client.get(f"/api/me/documents/{doc_id}/file", headers=other).status_code == 404
    # customer cannot review, officer can
    assert client.post(f"/api/officer/documents/{doc_id}/review", headers=h,
                       json={"verdict": "verify"}).status_code == 403
    off = login(client, "officer1", "Officer@123")
    assert client.get(f"/api/officer/documents/{doc_id}/file", headers=off).status_code == 200
    assert client.post(f"/api/officer/documents/{doc_id}/review", headers=off,
                       json={"verdict": "reject", "note": ""}).status_code == 400
    r = client.post(f"/api/officer/documents/{doc_id}/review", headers=off,
                    json={"verdict": "verify", "note": "seen original"})
    assert r.json()["status"] == "VERIFIED"


def test_pending_required_document_blocks_loan_approval(client):
    h, _ = make_customer(client, "pendingdoc1", docs=[])
    for doc_type in ("ADDRESS_PROOF", "INCOME_PROOF"):
        assert client.post("/api/me/documents/sample", json={"doc_type": doc_type}, headers=h).status_code == 200

    png = b"\x89PNG\r\n\x1a\n" + b"0" * 600
    upload = client.post("/api/me/documents", headers=h, data={"doc_type": "ID_PROOF"},
                         files={"file": ("id.png", png, "image/png")})
    assert upload.status_code == 200 and upload.json()["status"] == "UPLOADED"

    application = client.post("/api/me/applications", json=PERSONAL, headers=h).json()
    officer = login(client, "officer1", "Officer@123")
    result = client.post(f"/api/officer/applications/{application['id']}/decision", headers=officer,
                         json={"decision": "approve", "note": "", "override": False})
    assert result.status_code == 400
    assert "documents must be verified" in result.json()["detail"].lower()
    assert client.get("/api/me/loans", headers=h).json() == []


def test_sample_pdf_is_auto_verified_against_profile(client):
    h, _ = make_customer(client, "doctest2", docs=[])
    d = client.post("/api/me/documents/sample", json={"doc_type": "INCOME_PROOF"}, headers=h).json()
    assert d["status"] == "VERIFIED"
    names = {c["name"] for c in d["checks"]}
    assert {"Name matches profile", "Income vs declared"} <= names


def test_loan_fit_ranking(client):
    h = login(client, "rahul", "Cust@1234")
    r = client.get("/api/me/loan-fit?explain=true", headers=h).json()
    assert r["narrative_mode"] == "rules" and r["narrative"]
    assert r["obligations"]["our_active_loans"] > 0          # his existing personal loan is counted
    eligible = [o["ease_score"] for o in r["options"] if o["likelihood"] != "NOT_ELIGIBLE"]
    assert eligible and eligible == sorted(eligible, reverse=True)
    low = login(client, "vikram", "Cust@1234")
    rv = client.get("/api/me/loan-fit?explain=false", headers=low).json()
    assert next(o for o in rv["options"] if o["code"] == "PERSONAL")["likelihood"] == "NOT_ELIGIBLE"


def test_profile_view_edit_password(client):
    h = login(client, "anita", "Cust@1234")
    p = client.get("/api/me/profile", headers=h).json()
    assert p["pan"].startswith("DE") and "XXXXX" in p["pan"] and p["credit"]["band"]
    body = {"phone": "9876543210", "address": "5 Lake View", "city": "Kadapa", "pincode": "516001",
            "employer": "Acme", "employment_type": "SALARIED", "monthly_income": 90000, "existing_emi": 0}
    assert client.put("/api/me/profile", json=body, headers=h).json()["city"] == "Kadapa"
    assert client.put("/api/me/profile", json={**body, "phone": "123"}, headers=h).status_code == 422
    assert client.post("/api/me/password", headers=h,
                       json={"current_password": "wrong", "new_password": "Newpass12"}).status_code == 400


def test_foreclose_and_statement(client):
    h = login(client, "suresh", "Cust@1234")
    loan = client.get("/api/me/loans", headers=h).json()[0]
    csv = client.get(f"/api/me/loans/{loan['id']}/statement.csv", headers=h)
    assert csv.status_code == 200 and "Due date" in csv.text
    r = client.post(f"/api/me/loans/{loan['id']}/foreclose", headers=h)
    assert r.status_code == 400                                # balance too low for full payoff
    client.post("/api/me/accounts/demo", json={"balance": 5_000_000}, headers=h)
    r = client.post(f"/api/me/loans/{loan['id']}/foreclose", headers=h)
    assert r.status_code == 200
    after = client.get("/api/me/loans", headers=h).json()[0]
    assert after["status"] == "CLOSED" and after["outstanding"] == 0 and after["next_due"] is None


def test_customer_cannot_read_other_customers_loan(client):
    priya = login(client, "priya", "Cust@1234")
    pid = client.get("/api/me/loans", headers=priya).json()[0]["id"]
    rahul = login(client, "rahul", "Cust@1234")
    assert client.get(f"/api/me/loans/{pid}/schedule", headers=rahul).status_code == 404
    assert client.get(f"/api/me/loans/{pid}/payments", headers=rahul).status_code == 404


def test_service_request_rejects_nonpositive_loan_id(client):
    h = login(client, "rahul", "Cust@1234")
    result = client.post("/api/me/requests", headers=h, json={
        "category": "LOAN", "loan_id": 0, "subject": "Question", "message": "Need help"
    })
    assert result.status_code == 422


def test_frozen_account_diagnosis(client):
    h = login(client, "rahul", "Cust@1234")
    acc = client.get("/api/me/accounts", headers=h).json()[0]
    loan = client.get("/api/me/loans", headers=h).json()[0]
    admin = login(client, "admin", "Admin@123")
    client.post(f"/api/admin/accounts/{acc['id']}/freeze", headers=admin)
    d = client.get(f"/api/me/loans/{loan['id']}/autopay-status", headers=h).json()
    assert d["code"] == "ACCOUNT_FROZEN"
    client.post(f"/api/admin/accounts/{acc['id']}/freeze", headers=admin)


def test_agent_actions_need_server_side_confirmation(client):
    from app.database import SessionLocal
    from app.models import Loan, User
    from app.services import agent
    from app.services.agent import chat
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(username="rahul").first()
        loan = db.query(Loan).filter_by(user_id=user.id).first()
        tools = {t.__name__: t for t in agent.build_tools(db, user)}
        staged = tools["disable_autopay"](loan.id)
        assert staged["status"] == "AWAITING_USER_CONFIRMATION"
        db.refresh(loan)
        assert loan.autopay_enabled is True                       # model alone changed nothing
        assert chat(db, user, "no", [])["reply"].startswith("Cancelled")
        tools["disable_autopay"](loan.id)
        assert "OFF" in chat(db, user, "Yes", [])["reply"]        # only the user's own YES executes
        db.refresh(loan)
        assert loan.autopay_enabled is False
        tools["enable_autopay"](loan.id)
        assert "ON" in chat(db, user, "yes", [])["reply"]
        # a YES with nothing pending is just a normal message
        assert chat(db, user, "yes", [])["mode"] == "rules"
    finally:
        db.close()


def test_agent_prepayment_simulation_is_read_only_and_customer_scoped(client):
    from app.database import SessionLocal
    from app.models import Loan, User
    from app.services.agent import build_tools, chat

    db = SessionLocal()
    try:
        user = db.query(User).filter_by(username="rahul").first()
        loan = db.query(Loan).filter_by(user_id=user.id, status="ACTIVE").first()
        other_loan = db.query(Loan).filter(Loan.user_id != user.id, Loan.status == "ACTIVE").first()
        assert loan is not None and other_loan is not None
        balance_before = loan.account.balance
        outstanding_before = loan.outstanding

        tools = {tool.__name__: tool for tool in build_tools(db, user)}
        result = tools["simulate_prepayment"](loan.id, 50000)
        assert result["simulation"]["type"] == "PART_PREPAYMENT"
        assert result["simulation"]["reduce_emi"]["interest_saved"] > 0
        assert loan.account.balance == balance_before
        assert loan.outstanding == outstanding_before
        assert "interest" in chat(db, user, f"what if I pay Rs 50,000 extra on loan #{loan.id}?", []).get("reply", "").lower()

        unauthorized = tools["simulate_prepayment"](other_loan.id, 50000)
        assert "error" in unauthorized
        assert "not found" in unauthorized["error"].lower()
    finally:
        db.close()
