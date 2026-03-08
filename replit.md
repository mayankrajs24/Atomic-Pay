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
- **Frontend**: Jinja2 templates with vanilla JS, mobile-first design

## UI Design System
- **Theme**: Pure black (#000000) with glassmorphism, Inter + JetBrains Mono fonts
- **CSS Variables**: --accent (#6366f1 indigo), --green, --red, --gold for state badges
- **State Badges**: `.state-badge.sattva` (green), `.state-badge.tamas` (red), `.state-badge.rajas` (gold)
- **PIN Confirmation**: Full overlay with numeric keypad + WebAuthn biometric fallback
- **UPI Integration UI**: GPay/PhonePe/Paytm/AtomicPay integration cards
- **Toast Notifications**: Non-blocking success/error toasts
- **Animations**: screenIn, slideUp, scaleIn, popIn, glow, float, spin, pulse
- **SVG Icons**: All navigation and action icons use inline SVGs

## Payment Flow (Frontend)
1. `initiateSend()` - validates recipient + amount, stores PENDING_PAYMENT
2. `openPinConfirm()` - shows PIN keypad overlay
3. User enters 4-digit PIN on keypad (or uses biometric)
4. `verifyPinAndSend()` - calls `/api/login` to verify PIN, then `/api/pay`
5. `showResult()` - displays result sheet with state badge and details

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
    app.html               - Main wallet UI (mobile-first, PIN confirm overlay)
    admin.html             - Admin dashboard (tabbed, metrics grid)
    compliance.html        - Compliance dashboard (AML, fraud, KYC, reports)
    developer.html         - Developer portal / API docs / integration guide
  static/
    css/style.css           - Global design system (glassmorphism, state badges)
    js/app.js               - Main wallet JS (PIN flow, biometric, toasts)
sdk/
  atomicpay_bank_sdk.py    - Python Bank SDK
```

## Key API Endpoints
- POST /api/register, /api/login - Auth
- POST /api/pay - Atomic payment
- GET /api/balance, /api/history - Account info
- POST /api/link_bank - Link bank account
- POST /api/find_user - Search users
- /api/kyc/* - KYC verification
- /api/admin/* - Admin operations (requires admin role)
- /api/compliance/* - Compliance dashboard data
- /api/regulatory/* - Regulatory reports

## Security
- SESSION_SECRET env var is MANDATORY (no fallback)
- PBKDF2-SHA256 PIN hashing (replaced broken passlib/bcrypt)
- Login rate limiting: 5 attempts per 5-minute window
- Server-side admin role verification via `require_admin()` DB lookup
- PIN re-authentication required before every payment

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
