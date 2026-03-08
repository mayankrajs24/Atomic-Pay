# AtomicPay - Fintech Payment Platform v2.0

## Overview
AtomicPay is a production-grade fintech platform implementing a three-state atomic payment protocol:
- **-1 Tamas** (Reversed/Failed)
- **0 Rajas** (Transit - exists only during atomic window)
- **+1 Sattva** (Completed)

## Architecture
- **Backend**: FastAPI (Python) on port 5000
- **Database**: PostgreSQL via DATABASE_URL with connection pooling (pool_size=20, max_overflow=40, pool_recycle=300s)
- **Bank Simulators**: In-memory simulators on ports 6001 (Bank A) and 6002 (Bank B), started as daemon threads
- **Auth**: JWT tokens with PBKDF2-SHA256 PIN hashing
- **Frontend**: Jinja2 templates with vanilla JS, mobile-first design
- **Deployment**: Configured for Replit autoscale deployment

## Portal Architecture
Admin, compliance, and developer pages are separated from the user-facing app:
- **User App**: `/` — Consumer wallet (no admin links visible)
- **Admin Portal**: `/portal/admin` — Admin dashboard with bank onboarding, branch mgmt
- **Compliance Portal**: `/portal/compliance` — AML, fraud, KYC oversight
- **Developer Portal**: `/portal/developer` — API docs, integration guide
- **Bank Registration**: `/portal/bank-register` — Public self-registration for banks

Admin users see a "Portal" link in their profile screen.

## Production Hardening (v2.0)
- **Security Headers**: X-Content-Type-Options, X-Frame-Options, X-XSS-Protection, Referrer-Policy, Permissions-Policy, HSTS (production)
- **GZip Compression**: All responses > 500 bytes compressed
- **Request ID Tracking**: Every request gets X-Request-ID for traceability
- **Response Timing**: X-Response-Time header on all responses
- **API Rate Limiting**: 100 requests per 60 seconds per IP
- **Login Rate Limiting**: 5 attempts per 5-minute window per mobile
- **Global Exception Handler**: Structured error responses with request_id
- **Structured Logging**: Timestamped logs via Python logging (atomicpay.*)
- **Idempotency Keys**: Duplicate payment prevention via idempotency_key field
- **Daily Transaction Limits**: Rs.500K default, Rs.2M for KYC Level 2
- **Payment Amount Validation**: Min Rs.1, Max Rs.10L
- **HMAC Signatures**: Transaction signatures use SESSION_SECRET (not hardcoded)
- **Bank Call Retry**: 2 retries with timeout/connection error handling
- **Input Validation**: Pydantic v2 field validators with regex patterns, min/max lengths
- **Database Safety**: Automatic rollback on errors, statement/lock timeouts
- **Health Check**: /api/health endpoint for load balancer monitoring
- **Static File Caching**: 24-hour Cache-Control for static assets
- **API Cache Prevention**: no-store/no-cache for API responses
- **Account Suspension**: is_active check on login, failed_login_count tracking
- **Database Indexes**: Composite indexes on sender_mobile+created_at, audit timestamps
- **Swagger Docs**: Hidden in production (REPL_DEPLOYMENT=1)

## Branch & Multi-Account System
- **BankBranch model**: bank_id, branch_name, ifsc_code (11 chars, unique), branch_city, branch_state, branch_address
- **IFSC format**: 4-char bank code + 0 + 6-char branch code (e.g., SBIN0001234)
- **UserBankAccount model**: user_id, bank_id, branch_ifsc, account_id, account_type, account_label, is_primary
- Users can have multiple accounts (same bank, different branches, different types)
- Primary account used for payments by default, user can switch
- Unique constraint: (user_id, bank_id, account_id) — prevents duplicate links
- Backward compatible: User.bank_id / User.account_id still tracked for primary account

## Real Bank Onboarding
- Banks can self-register via `/portal/bank-register` (public, no auth required, status=pending)
- Admin also can register banks via admin dashboard
- Admin approves bank (status=active) → `_sync_bank_to_available()` adds to AVAILABLE_BANKS
- Bank model stores: api_key (apk_live_*), webhook_secret (whsec_*), environment, health_status
- Startup calls `load_active_banks_from_db()` to restore approved banks into AVAILABLE_BANKS
- Simulator banks (bank_a, bank_b) are NOT in DB — they remain via `start_bank_simulators()`
- Admin can suspend/reactivate banks, regenerate API keys, run health checks and connectivity tests
- Branch management: add branches with IFSC codes, view per-bank branch list
- All actions are audit-logged

## Project Structure
```
main.py                    - Entry point (runs uvicorn on port 5000)
backend/
  main.py                  - FastAPI app with all routes + exception handlers
  config.py                - Configuration (DB, JWT, limits, rate limiting)
  database.py              - SQLAlchemy engine with pool settings + PG timeouts
  models.py                - ORM models (Users, Banks, BankBranch, UserBankAccount, Transactions, KYC, AML, Fraud, Audit)
  auth.py                  - JWT auth + PBKDF2 PIN hashing
  payments.py              - Two-phase atomic payment engine with idempotency
  banks.py                 - Bank simulators + async bank calls with retry
  bank_connector.py        - Bank onboarding + branch mgmt + multi-account functions
  middleware.py             - RequestID, SecurityHeaders, RateLimit middleware
  fraud_detection.py       - Fraud scoring engine
  aml.py                   - Anti-money laundering checks
  kyc.py                   - KYC verification
  compliance.py            - Audit logging with error resilience
  monitoring.py            - System monitoring with fallback
  templates/
    app.html               - Main wallet UI (mobile-first, multi-account, PIN confirm overlay)
    admin.html             - Admin dashboard (bank onboarding, branch mgmt)
    compliance.html        - Compliance dashboard (AML, fraud, KYC, reports)
    developer.html         - Developer portal / API docs / integration guide
    bank_register.html     - Public bank self-registration portal
  static/
    css/style.css           - Global design system (glassmorphism, state badges)
    js/app.js               - Main wallet JS (multi-account, PIN flow, toasts)
sdk/
  atomicpay_bank_sdk.py    - Python Bank SDK
```

## Key API Endpoints
- GET /api/health - Health check (DB status, uptime)
- POST /api/register, /api/login - Auth
- POST /api/pay - Atomic payment (supports idempotency_key)
- GET /api/balance, /api/history - Account info
- POST /api/link_bank - Link bank account (also creates UserBankAccount)
- POST /api/accounts/add - Add additional bank account
- GET /api/accounts - List user's linked accounts
- POST /api/accounts/set_primary - Set default payment account
- DELETE /api/accounts/{id} - Remove a linked account
- GET /api/ifsc/{code} - IFSC code lookup
- POST /api/banks/self-register - Public bank self-registration
- /api/admin/banks/* - Bank management (register/approve/suspend/test/health/regenerate_key/branches)
- /api/compliance/* - Compliance dashboard data
- /api/regulatory/* - Regulatory reports

## Security
- SESSION_SECRET env var is MANDATORY (no fallback)
- PBKDF2-SHA256 PIN hashing with unique salts
- Login rate limiting: 5 attempts per 5-minute window
- API rate limiting: 100 requests per 60 seconds per IP
- Server-side admin role verification via `require_admin()` DB lookup
- PIN re-authentication required before every payment
- Security headers on all responses
- HMAC-SHA256 transaction signatures
- Admin/Compliance portals separated from user-facing app

## Demo Credentials
- Ram: 9876543210 / 1234 (Bank A, account RAM_001)
- Sita: 9876543211 / 1234 (Bank B, account SITA_001)
- Arjun: 9876543212 / 1234 (Bank A, account ARJUN_01)
- Admin: 0000000000 / admin123

## Dependencies
- fastapi, uvicorn, sqlalchemy, psycopg2-binary
- python-jose (JWT), hashlib/hmac (PIN hashing)
- httpx (async HTTP), jinja2 (templates)
- pydantic (validation)


## Installation

Install all required dependencies using pip:

```bash
pip install fastapi uvicorn sqlalchemy psycopg2-binary python-jose httpx jinja2 pydantic python-dotenv
```

### Dependency Description

| Package         | Purpose                                      |
| --------------- | -------------------------------------------- |
| fastapi         | Web framework for building the API           |
| uvicorn         | ASGI server to run the FastAPI app           |
| sqlalchemy      | ORM for database interactions                |
| psycopg2-binary | PostgreSQL database driver                   |
| python-jose     | JWT authentication handling                  |
| httpx           | Async HTTP client for API calls              |
| jinja2          | Template rendering engine                    |
| pydantic        | Data validation and schemas                  |
| python-dotenv   | Load environment variables from `.env` files |

## Environment Variables

Create a `.env` file in the root of the backend directory.

Example `.env` configuration:

```
DATABASE_URL=postgresql://postgres:Pass%40123@localhost:5432/atomicpay
SESSION_SECRET=your_super_secret_key
REPL_DEPLOYMENT=0
```

### Variable Description

| Variable        | Description                                              |
| --------------- | -------------------------------------------------------- |
| DATABASE_URL    | PostgreSQL database connection string                    |
| SESSION_SECRET  | Secret key used for JWT and session security             |
| REPL_DEPLOYMENT | Set to `1` when running in Replit production environment |

### Notes

* If your database password contains special characters like `@`, it must be URL encoded.
* Example: `Pass@123` → `Pass%40123`.
* Ensure the PostgreSQL database (`atomicpay`) exists before running the application.

### Run the Server

```
uvicorn main:app --reload
```

## Run Command
```
python main.py
```
