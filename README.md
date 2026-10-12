# Loan Lifecycle Guardian

Detailed project documentation is available in [docs/DEVELOPER_GUIDE.md](docs/DEVELOPER_GUIDE.md).

Loan Lifecycle Guardian is a demo banking application for the loan lifecycle, built with FastAPI, SQLAlchemy, and a single-page HTML/JavaScript frontend. Customers can explore products, check eligibility, apply, manage documents and repayments, while bank officers review applications and administrators manage the demo environment.

This repository is a functional prototype, not production banking software. Credit scores, bank balances, decisions, document checks, and payment processing are simulated. Do not use real customer data, credentials, or payment accounts with this application.

## Contents

- [Capabilities](#capabilities)
- [Architecture](#architecture)
- [Requirements and dependencies](#requirements-and-dependencies)
- [Run locally on Windows](#run-locally-on-windows)
- [Configuration](#configuration)
- [Demo accounts](#demo-accounts)
- [API overview](#api-overview)
- [Database and uploads](#database-and-uploads)
- [Tests](#tests)
- [Git and data protection](#git-and-data-protection)
- [Known limitations](#known-limitations)

## Capabilities

### Latest implementation status

This repository currently includes the proactive customer-insights workflow and the customer-scoped prepayment simulation tool, both wired into the app and frontend:

- `GET /api/me/insights` provides personalized Guardian alerts for upcoming or overdue EMIs, autopay issues, and application follow-up needs.
- The customer home page renders those alerts and exposes a demo action flow for payment, autopay, and account updates.
- The role-aware assistant can answer questions such as “what should I do next?” and “what happens if I pay Rs 50,000 extra?” using a read-only simulation tool.
- Prepayment calculations are customer-scoped and non-mutating: they estimate interest saved and repayment impact without changing the underlying loan or moving funds.
- The app keeps state-changing agent actions behind a separate confirmation step, which reduces accidental actions in demo mode.

### Customer

- Register and sign in; edit profile details and change password.
- Browse loan products, calculate an EMI, run eligibility pre-checks, and view ranked loan-fit suggestions.
- Apply for a loan using documents in the document locker.
- Upload PDF, PNG, or JPG files. Upload checks include content signatures, size, duplicate detection, and limited text-PDF checks. Documents that cannot be checked automatically are queued for officer review.
- View application status, loan schedule, payment history, account, and notifications.
- Enable or disable auto-pay, pay an installment manually, download a CSV statement, and request foreclosure.
- Ask the Guardian assistant questions about loan status, auto-pay failures, and prepayment what-if scenarios. Prepayment simulations compare reducing the EMI with reducing the remaining term and estimate interest saved; they do not move money or change the loan. State-changing agent actions are staged and require a separate customer confirmation message.
- View proactive Guardian alerts for upcoming/overdue EMIs, auto-pay problems, and applications needing information; available actions are constrained by demo mode and require user action.
- Submit customer support requests and password-reset requests.

### Officer

- View and prioritize the application queue, inspect eligibility checks and customer documents, request information, and make an approval or rejection decision.
- Verify or reject uploaded documents, update KYC, send reminders, and handle service requests.
- View dashboard and collection summaries.

### Administrator

- Manage staff and users, enable or disable user accounts, and initiate customer password resets.
- Review password-reset requests, freeze or unfreeze demo accounts, run the auto-pay engine, and inspect audit events.

Loan-fit ranking and eligibility decisions are based on application rules; the optional language model only generates explanatory text. The model does not approve loans or move money.

## Architecture

```text
Browser
  frontend/index.html (served at /; calls the JSON API)
        |
        v
FastAPI application (app/main.py)
  routers: auth, customer, officer, admin, agent
        |
        v
Services: eligibility, advisor, lifecycle, EMI, documents,
          auto-pay, notifications, portfolio, servicing, LLM
        |
        +--> SQLAlchemy database (SQLite by default)
        +--> uploads/ (document files, excluded from Git)
        +--> optional Gemini API
```

Important source areas:

- `app/main.py`: application initialization, startup database table creation, static frontend, health endpoint, optional scheduler.
- `app/config.py`: environment-variable configuration.
- `app/database.py`: SQLAlchemy engine, session factory, and request-scoped database sessions.
- `app/models.py` and `app/schemas.py`: database entities and request/response validation models.
- `app/security.py`: password hashing, JWT creation/validation, and role checks.
- `app/routers/`: API routes grouped by authentication, customer, officer, administrator, and agent responsibilities.
- `app/services/`: business logic for loan decisions, eligibility, lifecycle, schedules, documents, payments, notifications, insights, and the optional LLM.
- `frontend/index.html`: browser interface and API client; no separate frontend build is required.
- `db/migration_add_service_requests.sql`: one SQL Server migration for the service-request table. It is not a complete database schema migration system.
- `tests/`: endpoint and business-logic tests.

## Requirements and dependencies

Use Python 3.10 or later. SQLite is included with Python and is the default database.

Install the minimum application dependencies:

```powershell
py -3.10 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

`requirements.txt` contains the core runtime packages:

| Package | Purpose |
|---|---|
| `fastapi` | HTTP API and request handling |
| `uvicorn` | ASGI web server |
| `pydantic` | Request and data validation |
| `SQLAlchemy` | ORM and database connections |
| `PyJWT` | JWT authentication tokens |
| `python-dotenv` | Load local `.env` configuration |
| `python-multipart` | Multipart document uploads |

Optional packages are in `requirements-extra.txt`:

| Package | Install/use when |
|---|---|
| `google-genai` | Gemini explanations and function-calling assistant are wanted. Without it or a key, the app falls back to rules-based responses. |
| `pyodbc` | SQL Server is selected; a compatible Microsoft ODBC Driver must also be installed on the machine. |
| `psycopg2-binary` | PostgreSQL is selected. |

Install optional integrations only when needed:

```powershell
python -m pip install -r requirements-extra.txt
```

For development and tests, install `requirements-dev.txt`; it includes the core requirements, `httpx` for FastAPI's test client, and `pytest`:

```powershell
python -m pip install -r requirements-dev.txt
```

The Python dependency files declare supported minimum versions rather than locking a byte-for-byte reproducible environment. A lock file can be added later if deployment reproducibility is required.

## Run locally on Windows

1. Create and activate a virtual environment and install `requirements-dev.txt` as above.
2. Optionally copy `.env.example` to `.env` and edit its settings. The defaults use SQLite and do not need a Gemini key.
3. Start the app:

   ```powershell
   python run.py
   ```

4. Open `http://127.0.0.1:8000`. The API reference is at `http://127.0.0.1:8000/docs`, and the health check is `http://127.0.0.1:8000/api/health`.

On first startup, SQLAlchemy creates missing tables. When demo seeding is enabled, sample products, users, applications, loans, and sample documents are created if the user table is empty. Existing databases are not automatically upgraded when model columns change; back up data and apply an appropriate migration before using a changed schema.

## Configuration

All settings are read from process environment variables and, when present, `.env`:

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./loan_guardian.db` | SQLAlchemy database URL. SQLite is the local default. |
| `JWT_SECRET` | Development-only secret in code | Signing secret for session tokens. Set a unique, long random value outside a local demo. With `DEMO_MODE=0`, startup rejects the built-in development secret. |
| `JWT_EXPIRE_MIN` | `120` | JWT lifetime in minutes. |
| `DEMO_MODE` | `1` | Enables demo-specific behavior and sample-document tooling. |
| `SEED_DEMO` | `1` | Seeds sample records when the database has no users. Set to `0` to disable. |
| `GEMINI_API_KEY` / `GOOGLE_API_KEY` | unset | Optional Gemini credential. Either variable is accepted. Do not commit a real key. |
| `GEMINI_MODEL` | `gemini-3.8-flash` | Gemini model name; can be overridden in `.env` or the process environment. |
| `AUTOPAY_SCHEDULER_SECONDS` | `0` | `0` disables the background scheduler; a positive value is the interval in seconds. |
| `MAX_AUTOPAY_ATTEMPTS` | `5` | Maximum simulated auto-debit attempts per installment. |
| `UPLOAD_DIR` | `./uploads` | Local storage path for uploaded documents. |
| `MAX_UPLOAD_MB` | `5` | Maximum accepted document size in megabytes. |

Set environment variables in PowerShell for the current terminal session, for example:

```powershell
$env:JWT_SECRET = "use-a-unique-long-random-value-here"
$env:DEMO_MODE = "0"
$env:SEED_DEMO = "0"
```

For a Gemini-enabled session, set `$env:GEMINI_API_KEY` directly in your terminal or use a private local `.env`; never put a real credential in `.env.example` or commit it.

Database examples (install the matching optional driver first):

```dotenv
# SQLite (default)
DATABASE_URL=sqlite:///./loan_guardian.db

# PostgreSQL
DATABASE_URL=postgresql+psycopg2://user:password@host/database?sslmode=require

# SQL Server; requires a configured ODBC driver and a database created by the operator
DATABASE_URL=mssql+pyodbc://@localhost\SQLEXPRESS/LoanGuardian?driver=ODBC+Driver+17+for+SQL+Server&trusted_connection=yes&TrustServerCertificate=yes
```

## Demo accounts

These fixed credentials are created by `app/seed.py` and are for local demonstrations only. Disable demo seeding and use a fresh database before exposing an instance to anyone else.

| Role | Username | Password |
|---|---|---|
| Administrator | `admin` | `Admin@123` |
| Officer | `officer1` | `Officer@123` |
| Customer | `rahul`, `priya`, `suresh`, `anita`, `vikram` | `Cust@1234` |

The seeded accounts illustrate different situations such as insufficient funds, disabled net banking, a successful payment, an approvable application, and a rejected recommendation. Do not reuse these accounts or passwords in a deployed environment.

## API overview

All API routes are under `/api`. Authenticated routes use a bearer JWT in the `Authorization` header. Role checks are enforced on the server.

| Route group | Example paths | Access / purpose |
|---|---|---|
| Authentication | `/api/auth/register`, `/api/auth/login`, `/api/auth/me` | Registration, login, and current user. |
| Customer | `/api/products`, `/api/me/profile`, `/api/me/loan-fit`, `/api/me/insights`, `/api/me/applications`, `/api/me/loans`, `/api/me/documents`, `/api/me/requests` | Customer profile, eligibility, proactive alerts, applications, loans, documents, notifications, and support. |
| Officer | `/api/officer/applications`, `/api/officer/documents/{id}/review`, `/api/officer/dashboard`, `/api/officer/requests` | Application/document review and servicing; officer or administrator role. |
| Administrator | `/api/admin/users`, `/api/admin/run-autopay`, `/api/admin/audit`, `/api/admin/password-reset-requests` | User administration, simulated collections, audit, and password resets. |
| Agent | `/api/agent/chat` | Role-aware assistant for signed-in users. |
| Health | `/api/health` | Service status and whether Gemini is configured. |

See `/docs` for the complete generated OpenAPI schema and request models.

## Database and uploads

- The default local database is `loan_guardian.db` in the working directory. SQLite files are intentionally ignored by Git.
- Uploaded files live under `uploads/` by default; test uploads live under `test_uploads/`. These paths are intentionally ignored because they can contain personal information.
- The app creates missing tables at startup, but `create_all` does not alter an existing schema. Back up and migrate an existing database before updating models.
- The only checked-in SQL migration is `db/migration_add_service_requests.sql`, intended to add the service-request table to an existing SQL Server database. This repository does not currently include `db/schema_mssql.sql` or a general-purpose migration framework.
- For a disposable local demo, remove the local database and restart to reseed from scratch. This permanently deletes local demo data; do not do this to a database that contains data you need.

## Tests

Run the test suite from the repository root with the project virtual environment active:

```powershell
python -m pytest -q
```

Tests use a separate SQLite database (`test_guardian.db`) and upload directory (`test_uploads/`). They cover EMI calculations, role authorization, validation, loan decisions, auto-pay outcomes, document checks/review, customer isolation, loan-fit ranking, service requests, confirmation-gated agent actions, and read-only customer-scoped prepayment simulations. Approval now rejects required documents still awaiting officer verification, and linked service-request loan IDs must be positive and owned by the customer.

## Git and data protection

### Normally commit

- Application source under `app/`.
- Frontend source under `frontend/`.
- Tests under `tests/`.
- Safe configuration template `.env.example` (placeholders only).
- Dependency manifests (`requirements.txt`, `requirements-extra.txt`, `requirements-dev.txt`).
- Documentation, SQL migrations, and the small launcher (`README.md`, `db/`, `run.py`).

### Keep out of Git

The checked-in `.gitignore` excludes these generated or sensitive items:

- `.env` and other `.env.*` files, except the explicitly allowed `.env.example` template.
- `.venv/`, other local virtual environments, Python bytecode/cache, test cache, coverage reports, build output, and package metadata.
- Local SQLite/database files such as `*.db`, `*.sqlite`, and `*.sqlite3`.
- `uploads/` and `test_uploads/`, which may contain identity, address, income, or other customer documents.
- Private key/certificate files such as `*.pem`, `*.key`, `*.p12`, and `*.pfx`.

Do not add API keys, JWT secrets, production database URLs/passwords, real identity documents, customer records, or downloaded virtual environments to Git. If a secret was committed previously, removing the file in a later commit does not make the secret safe: revoke/rotate it and remove it from Git history as appropriate.

Before your first push, review the exact staged file list and ensure the ignored data is not already tracked:

```powershell
git status --short
git check-ignore -v .env loan_guardian.db uploads test_uploads .venv
git ls-files
```

If the repository has no Git history yet, initialize and push to a remote you created:

```powershell
git init
git add .
git status --short
git diff --cached --stat
git commit -m "Prepare Loan Lifecycle Guardian for Git"
git branch -M main
git remote add origin <your-repository-url>
git push -u origin main
```

If it is already a Git repository, do not run `git init` or overwrite its remote. Review `git status`, stage only the intended files, inspect the staged diff, then commit and push to the configured remote.

## Known limitations

- Credit score calculation is a simulation; profile income and external loan obligations are self-reported.
- Document verification is intentionally limited: it checks file signatures and simple uncompressed text PDFs, not OCR, document authenticity, or official KYC records. Other files need manual review.
- Loan balances and payment execution are simulated. No real bank, payment network, bureau, or mandate provider is connected.
- Monetary values use floating-point fields and should be changed to decimal/numeric types for financial-grade calculations.
- The auto-pay scheduler and pending assistant confirmations are in-memory and designed for a single process, not multiple workers.
- Manual payment and auto-pay use database row locks where the selected database supports them; SQLite does not provide equivalent row-level locking. This prototype is not designed for concurrent financial transactions or multi-worker deployment.
- Foreclosure is based on outstanding principal; accrued interest within the current month and partial prepayment are not modelled.
- Login throttling is in-memory and should be replaced with shared persistent rate limiting for multi-worker deployment.
- Unauthenticated password-reset requests are deduplicated while one request is pending, but the endpoint has no IP/account rate limit; add shared throttling before public deployment.
- Password changes and resets update the stored password, but currently issued JWTs remain valid until their expiry (120 minutes by default) unless the account is deactivated. Add token revocation/session versioning before using this design beyond a demo.
- Seeded sample documents and fixed demo credentials are not production records or secure account defaults.
- Production use would require proper schema migrations, secret management, persistent storage, robust KYC/OCR integration, observability, deployment hardening, and independent security and financial review.