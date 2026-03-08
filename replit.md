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

## UI Design System
- **Theme**: Pure black (#000000) with glassmorphism, Inter + JetBrains Mono fonts
- **CSS Variables**: --accent (#6366f1 indigo), --green, --red, --gold for state badges
- **State Badges**: `.state-badge.sattva` (green), `.state-badge.tamas` (red), `.state-badge.rajas` (gold)
- **PIN Confirmation**: Full overlay with numeric keypad
- **UPI Integration UI**: GPay/PhonePe/Paytm/AtomicPay integration cards
- **Toast Notifications**: Non-blocking success/error toasts
- **SVG Icons**: All navigation and action icons use inline SVGs

## Payment Flow (Frontend)
1. `initiateSend()` - validates recipient + amount, stores PENDING_PAYMENT
2. `openPinConfirm()` - shows PIN keypad overlay
3. User enters 4-digit PIN on keypad
4. `verifyPinAndSend()` - calls `/api/login` to verify PIN, then `/api/pay`
5. `showResult()` - displays result sheet with state badge and details

## Project Structure
```
main.py                    - Entry point (runs uvicorn on port 5000)
backend/
  main.py                  - FastAPI app with all routes + exception handlers
  config.py                - Configuration (DB, JWT, limits, rate limiting)
  database.py              - SQLAlchemy engine with pool settings + PG timeouts
  models.py                - ORM models (Users, Banks, Transactions, KYC, AML, Fraud, Audit)
  auth.py                  - JWT auth + PBKDF2 PIN hashing
  payments.py              - Two-phase atomic payment engine with idempotency
  banks.py                 - Bank simulators + async bank calls with retry
  bank_connector.py        - Real bank onboarding lifecycle (register/approve/suspend/test/health)
  middleware.py             - RequestID, SecurityHeaders, RateLimit middleware
  fraud_detection.py       - Fraud scoring engine
  aml.py                   - Anti-money laundering checks
  kyc.py                   - KYC verification
  compliance.py            - Audit logging with error resilience
  monitoring.py            - System monitoring with fallback
  templates/
    app.html               - Main wallet UI (mobile-first, PIN confirm overlay)
    admin.html             - Admin dashboard (tabbed, metrics grid)
    compliance.html        - Compliance dashboard (AML, fraud, KYC, reports)
    developer.html         - Developer portal / API docs / integration guide
  static/
    css/style.css           - Global design system (glassmorphism, state badges)
    js/app.js               - Main wallet JS (PIN flow, toasts)
sdk/
  atomicpay_bank_sdk.py    - Python Bank SDK
```

## Key API Endpoints
- GET /api/health - Health check (DB status, uptime)
- GET /api/ping - Simple liveness check
- POST /api/register, /api/login - Auth
- POST /api/pay - Atomic payment (supports idempotency_key)
- GET /api/balance, /api/history - Account info
- POST /api/link_bank - Link bank account
- POST /api/find_user - Search users
- /api/kyc/* - KYC verification
- /api/admin/* - Admin operations (requires admin role)
- /api/admin/banks/register - Register a new real bank (generates API key + webhook secret)
- /api/admin/banks/approve - Approve a pending bank (syncs to AVAILABLE_BANKS)
- /api/admin/banks/suspend - Suspend an active bank
- /api/admin/banks/test - Run connectivity tests against a bank
- /api/admin/banks/health_check - Ping a bank and update health status
- /api/admin/banks/regenerate_key - Regenerate a bank's API key
- /api/admin/banks/registered - List all registered banks
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

## Real Bank Onboarding
- Banks register via admin dashboard or API (status=pending)
- Admin approves bank (status=active) → `_sync_bank_to_available()` adds to AVAILABLE_BANKS
- Bank model stores: api_key (apk_live_*), webhook_secret (whsec_*), environment, health_status
- Startup calls `load_active_banks_from_db()` to restore approved banks into AVAILABLE_BANKS
- Simulator banks (bank_a, bank_b) are NOT in DB — they remain via `start_bank_simulators()`
- Admin can suspend/reactivate banks, regenerate API keys, run health checks and connectivity tests
- All actions are audit-logged

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

## Run Command
```
python main.py
```
