# AtomicPay - Fintech Payment Platform

## Overview
AtomicPay is a fintech platform implementing a three-state atomic payment protocol:
- **-1 Tamas** (Reversed/Failed)
- **0 Rajas** (Transit - exists only during atomic window)
- **+1 Sattva** (Completed)

## Architecture
- **Backend**: FastAPI (Python) on port 5000
- **Database**: PostgreSQL via DATABASE_URL
- **Bank Simulators**: In-memory simulators on ports 6001 (Bank A) and 6002 (Bank B), started as daemon threads
- **Auth**: JWT tokens with PBKDF2-SHA256 PIN hashing
- **Frontend**: Jinja2 templates with vanilla JS

## Project Structure
```
main.py                    - Entry point (runs uvicorn on port 5000)
backend/
  main.py                  - FastAPI app with all routes
  config.py                - Configuration (DB URL, JWT settings)
  database.py              - SQLAlchemy engine/session setup
  models.py                - ORM models (Users, Banks, Transactions, KYC, AML, Fraud, Audit)
  auth.py                  - JWT auth + PBKDF2 PIN hashing
  payments.py              - Two-phase atomic payment engine
  banks.py                 - Bank simulators + async bank calls
  fraud_detection.py       - Fraud scoring engine
  aml.py                   - Anti-money laundering checks
  kyc.py                   - KYC verification
  compliance.py            - Compliance reporting
  monitoring.py            - System monitoring
  templates/
    app.html               - Main wallet UI
    admin.html             - Admin dashboard
    compliance.html        - Compliance dashboard
    developer.html         - Developer portal / API docs
  static/
    css/style.css           - Global styles
    js/app.js               - Main wallet JS
sdk/
  atomicpay_bank_sdk.py    - Python Bank SDK
```

## Key API Endpoints
- POST /api/register, /api/login - Auth
- POST /api/pay - Atomic payment
- GET /api/balance, /api/history - Account info
- POST /api/link_bank - Link bank account
- GET /api/find_user - Search users
- /api/kyc/* - KYC verification
- /api/admin/* - Admin operations (requires admin role)
- /api/compliance/* - Compliance dashboard data
- /api/regulatory/* - Regulatory reports

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
