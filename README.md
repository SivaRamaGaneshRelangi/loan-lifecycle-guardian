# Loan Lifecycle Guardian

Loan Lifecycle Guardian is a prototype banking agent that investigates loan lifecycle events, checks policy guardrails, proposes actions for human approval, and records audit events.

## Features

* Loan and customer record lookup
* EMI payment and mandate investigation
* Loan onboarding and collateral checks
* Policy-based guardrails
* Human approval and rejection workflow
* Audit event logging

## Tech Stack

* Python 3.10+
* FastAPI
* Uvicorn
* Pydantic

## Prerequisites

* Python 3.10 or later
* Git

## Installation and Setup

### 1. Clone the repository

```bash
git clone YOUR_GITHUB_REPOSITORY_URL
cd loan-lifecycle-guardian
```

Replace `YOUR_GITHUB_REPOSITORY_URL` with your actual GitHub repository URL.

### 2. Create a virtual environment

**Windows PowerShell:**

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### 3. Install dependencies

```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### 4. Start the backend

Run this command from the project root:

```bash
python -m uvicorn backend.main:app --reload
```

### 5. Open the API documentation

Visit:

http://127.0.0.1:8000/docs

## Demo Workflow

1. Use `POST /agent/investigate/{loan_id}` to investigate a loan.
2. Review the customer, loan, EMI, payment, mandate, ledger, and policy findings.
3. Inspect the proposed action and guardrail status.
4. Use `GET /agent/approvals` to view pending human approval requests.
5. Submit a decision through `POST /agent/approvals/{request_id}/decision`.
6. Use `GET /agent/audit` to view recorded audit events.

### Example Demo Scenarios

* `L1003` — EMI payment failure and inactive mandate
* `L1002` — Incomplete onboarding documentation
* `L1004` — Loan closure blocked by an active collateral lien
* `L1001` — Routine loan review

## Important Notes

This is a prototype using fictional sample data and a deterministic, rule-based workflow. It is not yet a production banking system or a fully implemented LLM-based agent.

Approval requests and audit events are stored in memory and are cleared when the server restarts. Proposed actions are not executed against real banking systems. Guardrails prevent certain unsafe actions from being approved in the demo.

## Project Structure

* `backend/` — FastAPI application, API routes, agent workflow, tools, services, and sample data
* `policies/` — Policy documents used by the demo workflow
* `tests/` — Tests, if present

## Disclaimer

For demonstration and educational purposes only. Not intended for real financial transactions or production banking use.
