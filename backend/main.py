import logging
import sys
import os
import time
import traceback
from collections import defaultdict
from datetime import datetime

from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import desc
from pydantic import BaseModel, Field, field_validator
from typing import Optional

from backend.config import IS_PRODUCTION
from backend.database import get_db, init_db
from backend.models import User, Transaction, Bank, KYCRecord, AMLAlert, FraudFlag, AuditLog
from backend.auth import hash_pin, verify_pin, create_token, get_current_user, get_optional_user
from backend.banks import (
    AVAILABLE_BANKS, start_bank_simulators, verify_account,
    get_bank_balance, ping_bank, get_bank_logs, get_all_bank_accounts
)
from backend.payments import execute_payment
from backend.kyc import submit_kyc_document, verify_kyc_document
from backend.monitoring import get_system_metrics
from backend.compliance import log_audit
from backend.middleware import RequestIdMiddleware, SecurityHeadersMiddleware, RateLimitMiddleware
from backend.bank_connector import (
    register_bank, approve_bank, suspend_bank, regenerate_api_key,
    health_check_bank, test_bank_connection, load_active_banks_from_db,
    get_all_registered_banks, register_branch, register_branches_bulk,
    get_branches_by_bank, lookup_by_ifsc, add_user_account,
    get_user_accounts, set_primary_account, remove_user_account,
    get_primary_account
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
)
logger = logging.getLogger("atomicpay")

app = FastAPI(
    title="AtomicPay",
    version="2.0.0",
    description="The World's First -1/0/+1 Atomic Payment System",
    docs_url="/api/docs" if not IS_PRODUCTION else None,
    redoc_url="/api/redoc" if not IS_PRODUCTION else None,
)

app.add_middleware(GZipMiddleware, minimum_size=500)
app.add_middleware(RequestIdMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RateLimitMiddleware)

LOGIN_ATTEMPTS = defaultdict(list)
MAX_LOGIN_ATTEMPTS = 5
LOGIN_WINDOW_SECONDS = 300


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def check_rate_limit(mobile: str):
    now = time.time()
    LOGIN_ATTEMPTS[mobile] = [t for t in LOGIN_ATTEMPTS[mobile] if now - t < LOGIN_WINDOW_SECONDS]
    if len(LOGIN_ATTEMPTS[mobile]) >= MAX_LOGIN_ATTEMPTS:
        raise HTTPException(429, "Too many login attempts. Try again in 5 minutes.")


def record_login_attempt(mobile: str):
    LOGIN_ATTEMPTS[mobile].append(time.time())


def require_admin(user_data: dict, db: Session):
    user = db.query(User).filter(User.mobile == user_data["sub"]).first()
    if not user or user.role != "admin":
        raise HTTPException(403, "Admin access required")
    return user


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    request_id = getattr(request.state, "request_id", "unknown")
    logger.error(f"[{request_id}] Unhandled error: {exc}\n{traceback.format_exc()}")
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "request_id": request_id},
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    request_id = getattr(request.state, "request_id", "unknown")
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail, "request_id": request_id},
    )


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))


class RegisterRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    mobile: str = Field(..., min_length=10, max_length=15, pattern=r"^\d{10,15}$")
    pin: str = Field(..., min_length=4, max_length=20)
    email: Optional[str] = None

    @field_validator("name")
    @classmethod
    def clean_name(cls, v):
        v = v.strip()
        if not v:
            raise ValueError("Name cannot be empty")
        return v


class LoginRequest(BaseModel):
    mobile: str = Field(..., min_length=10, max_length=15)
    pin: str = Field(..., min_length=4, max_length=20)


class LinkBankRequest(BaseModel):
    bank_id: str = Field(..., min_length=1, max_length=50)
    account_id: str = Field(..., min_length=1, max_length=100)


class PayRequest(BaseModel):
    receiver_mobile: str = Field(..., min_length=10, max_length=15)
    amount: float = Field(..., gt=0)
    note: Optional[str] = Field("", max_length=500)
    idempotency_key: Optional[str] = Field(None, max_length=64)


class FindUserRequest(BaseModel):
    mobile: str = Field(..., min_length=10, max_length=15)


class KYCSubmitRequest(BaseModel):
    document_type: str = Field(..., min_length=1, max_length=20)
    document_number: str = Field(..., min_length=1, max_length=50)


class KYCVerifyRequest(BaseModel):
    record_id: int
    approve: bool


class AMLActionRequest(BaseModel):
    alert_id: int
    action: str = Field(..., pattern=r"^(resolved|dismissed)$")


class BankRegisterRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=200)
    bank_id: str = Field(..., min_length=2, max_length=50, pattern=r"^[a-z0-9_]+$")
    api_url: str = Field(..., min_length=5, max_length=500)
    short_code: Optional[str] = Field(None, max_length=10)
    public_key: Optional[str] = None
    contact_email: Optional[str] = None
    contact_name: Optional[str] = None
    environment: Optional[str] = Field("sandbox", pattern=r"^(sandbox|production)$")
    icon: Optional[str] = None
    color: Optional[str] = None


class BankActionRequest(BaseModel):
    bank_id: str = Field(..., min_length=2, max_length=50)
    reason: Optional[str] = Field(None, max_length=500)


class BankSelfRegisterRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=200)
    bank_id: str = Field(..., min_length=2, max_length=50, pattern=r"^[a-z0-9_]+$")
    api_url: str = Field(..., min_length=5, max_length=500)
    ifsc_prefix: Optional[str] = Field(None, min_length=4, max_length=4, pattern=r"^[A-Z]{4}$")
    short_code: Optional[str] = Field(None, max_length=10)
    contact_name: str = Field(..., min_length=2, max_length=200)
    contact_email: str = Field(..., min_length=5, max_length=255)
    environment: Optional[str] = Field("sandbox", pattern=r"^(sandbox|production)$")


class BranchRegisterRequest(BaseModel):
    branch_name: str = Field(..., min_length=2, max_length=200)
    ifsc_code: str = Field(..., min_length=11, max_length=11, pattern=r"^[A-Z]{4}0[A-Z0-9]{6}$")
    branch_city: Optional[str] = Field(None, max_length=100)
    branch_state: Optional[str] = Field(None, max_length=100)
    branch_address: Optional[str] = Field(None, max_length=500)


class BranchBulkItem(BaseModel):
    branch_name: str = Field(..., min_length=2, max_length=200)
    ifsc_code: str = Field(..., min_length=11, max_length=11, pattern=r"^[A-Z]{4}0[A-Z0-9]{6}$")
    branch_city: Optional[str] = Field(None, max_length=100)
    branch_state: Optional[str] = Field(None, max_length=100)
    branch_address: Optional[str] = Field(None, max_length=500)


class BranchBulkRequest(BaseModel):
    bank_id: str = Field(..., min_length=2, max_length=50)
    branches: list[BranchBulkItem]


class AddAccountRequest(BaseModel):
    bank_id: str = Field(..., min_length=1, max_length=50)
    account_id: str = Field(..., min_length=1, max_length=100)
    branch_ifsc: Optional[str] = Field(None, min_length=11, max_length=11)
    account_type: Optional[str] = Field("savings", pattern=r"^(savings|current|salary|fd|rd)$")
    account_label: Optional[str] = Field(None, max_length=100)


class SetPrimaryRequest(BaseModel):
    account_id: int


@app.on_event("startup")
async def startup():
    init_db()
    start_bank_simulators()
    from backend.database import SessionLocal
    db = SessionLocal()
    try:
        load_active_banks_from_db(db)
    except Exception as e:
        logger.warning(f"Could not load banks from DB: {e}")
    finally:
        db.close()
    logger.info("Database initialized")
    logger.info(f"Gateway ready on port 5000 (production={IS_PRODUCTION})")


@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    return templates.TemplateResponse("app.html", {"request": request})


@app.get("/portal/admin", response_class=HTMLResponse)
async def admin_page(request: Request):
    return templates.TemplateResponse("admin.html", {"request": request})


@app.get("/portal/compliance", response_class=HTMLResponse)
async def compliance_page(request: Request):
    return templates.TemplateResponse("compliance.html", {"request": request})


@app.get("/portal/developer", response_class=HTMLResponse)
async def developer_page(request: Request):
    return templates.TemplateResponse("developer.html", {"request": request})


@app.get("/portal/bank-register", response_class=HTMLResponse)
async def bank_register_page(request: Request):
    return templates.TemplateResponse("bank_register.html", {"request": request})


@app.get("/api/health")
async def health_check(db: Session = Depends(get_db)):
    try:
        db.execute(__import__("sqlalchemy").text("SELECT 1"))
        db_status = "healthy"
    except Exception:
        db_status = "unhealthy"

    return {
        "status": "healthy" if db_status == "healthy" else "degraded",
        "service": "AtomicPay Gateway",
        "version": "2.0.0",
        "database": db_status,
        "uptime": round(time.time() - __import__("backend.monitoring", fromlist=["_start_time"])._start_time),
    }


@app.get("/api/ping")
async def ping():
    return {"state": 1, "service": "AtomicPay Gateway", "version": "2.0.0"}


@app.get("/api/banks")
async def list_banks():
    banks = []
    for b in AVAILABLE_BANKS.values():
        online = await ping_bank(b["url"])
        banks.append({
            "id": b["id"], "name": b["name"], "short": b["short"],
            "label": b["label"], "color": b["color"], "icon": b["icon"],
            "online": online
        })
    return banks


@app.post("/api/register")
async def register(req: RegisterRequest, request: Request, db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.mobile == req.mobile).first()
    if existing:
        raise HTTPException(409, "Mobile number already registered")

    colors = ["#3b7fff", "#f472b6", "#34d399", "#f59e0b", "#a78bfa", "#fb923c"]
    color = colors[sum(ord(c) for c in req.name) % len(colors)]

    user = User(
        name=req.name.strip(),
        mobile=req.mobile.strip(),
        pin_hash=hash_pin(req.pin),
        email=req.email,
        avatar_color=color,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    ip = _client_ip(request)
    log_audit(db, "USER_REGISTERED", req.mobile, f"name={req.name}", ip_address=ip)
    logger.info(f"User registered: {req.mobile} ({req.name})")

    token = create_token({"sub": user.mobile, "name": user.name, "role": user.role, "user_id": user.id})
    return {
        "state": 1, "name": user.name, "mobile": user.mobile,
        "token": token, "bank_linked": False
    }


@app.post("/api/login")
async def login(req: LoginRequest, request: Request, db: Session = Depends(get_db)):
    mobile = req.mobile.strip()
    check_rate_limit(mobile)

    user = db.query(User).filter(User.mobile == mobile).first()
    if not user:
        record_login_attempt(mobile)
        raise HTTPException(404, "User not found")

    if not user.is_active:
        raise HTTPException(403, "Account is suspended")

    if not verify_pin(req.pin, user.pin_hash):
        record_login_attempt(mobile)
        user.failed_login_count = (user.failed_login_count or 0) + 1
        user.last_failed_login = datetime.utcnow()
        db.commit()
        logger.warning(f"Failed login attempt for {mobile}")
        raise HTTPException(401, "Wrong PIN")

    if user.failed_login_count and user.failed_login_count > 0:
        user.failed_login_count = 0
        db.commit()

    bank = AVAILABLE_BANKS.get(user.bank_id or "", {})
    token = create_token({"sub": user.mobile, "name": user.name, "role": user.role, "user_id": user.id})

    ip = _client_ip(request)
    log_audit(db, "USER_LOGIN", req.mobile, "Login successful", ip_address=ip)

    return {
        "state": 1, "name": user.name, "mobile": user.mobile,
        "bank_linked": user.bank_id is not None,
        "bank_id": user.bank_id, "bank_name": bank.get("name", ""),
        "bank_label": bank.get("label", ""),
        "account_id": user.account_id or "",
        "avatar_color": user.avatar_color,
        "kyc_level": user.kyc_level,
        "role": user.role,
        "token": token
    }


@app.post("/api/link_bank")
async def link_bank(req: LinkBankRequest, request: Request,
                    user_data=Depends(get_current_user), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.mobile == user_data["sub"]).first()
    if not user:
        raise HTTPException(404, "User not found")

    if req.bank_id not in AVAILABLE_BANKS:
        raise HTTPException(400, "Bank not found")

    account_id_clean = req.account_id.strip().upper()
    ok, result = await verify_account(req.bank_id, account_id_clean)
    if not ok:
        raise HTTPException(400, result)

    acc_result = add_user_account(db, user.id, {
        "bank_id": req.bank_id,
        "account_id": account_id_clean,
        "account_type": "savings",
    })

    if acc_result.get("is_primary", False) or not user.bank_id:
        user.bank_id = req.bank_id
        user.account_id = account_id_clean
        db.commit()

    bank = AVAILABLE_BANKS[req.bank_id]
    ip = _client_ip(request)
    log_audit(db, "BANK_LINKED", user.mobile, f"bank={req.bank_id} acc={account_id_clean}", ip_address=ip)
    return {
        "state": 1, "account_id": account_id_clean,
        "bank_name": bank["name"], "bank_label": bank["label"],
        "holder": result
    }


@app.post("/api/accounts/add")
async def api_add_account(req: AddAccountRequest, request: Request,
                          user_data=Depends(get_current_user), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.mobile == user_data["sub"]).first()
    if not user:
        raise HTTPException(404, "User not found")

    if req.bank_id not in AVAILABLE_BANKS:
        raise HTTPException(400, "Bank not found")

    account_id_clean = req.account_id.strip().upper()
    ok, holder = await verify_account(req.bank_id, account_id_clean)
    if not ok:
        raise HTTPException(400, holder)

    result = add_user_account(db, user.id, {
        "bank_id": req.bank_id,
        "account_id": account_id_clean,
        "branch_ifsc": req.branch_ifsc,
        "account_type": req.account_type or "savings",
        "account_label": req.account_label,
    })
    if not result["success"]:
        raise HTTPException(400, result["reason"])

    if result.get("is_primary") and (not user.bank_id or not user.account_id):
        user.bank_id = req.bank_id
        user.account_id = account_id_clean
        db.commit()

    ip = _client_ip(request)
    log_audit(db, "ACCOUNT_ADDED", user.mobile,
              f"bank={req.bank_id} acc={account_id_clean} type={req.account_type}", ip_address=ip)

    bank = AVAILABLE_BANKS[req.bank_id]
    return {
        "state": 1, "id": result["id"], "account_id": account_id_clean,
        "bank_name": bank["name"], "holder": holder,
        "is_primary": result["is_primary"],
    }


@app.get("/api/accounts")
async def api_list_accounts(user_data=Depends(get_current_user), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.mobile == user_data["sub"]).first()
    if not user:
        raise HTTPException(404, "User not found")
    return get_user_accounts(db, user.id)


@app.post("/api/accounts/set_primary")
async def api_set_primary(req: SetPrimaryRequest, request: Request,
                          user_data=Depends(get_current_user), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.mobile == user_data["sub"]).first()
    if not user:
        raise HTTPException(404, "User not found")

    result = set_primary_account(db, user.id, req.account_id)
    if not result["success"]:
        raise HTTPException(400, result["reason"])

    user.bank_id = result["bank_id"]
    user.account_id = result["primary_account_id"]
    db.commit()

    ip = _client_ip(request)
    log_audit(db, "PRIMARY_ACCOUNT_CHANGED", user.mobile,
              f"bank={result['bank_id']} acc={result['primary_account_id']}", ip_address=ip)
    return result


@app.delete("/api/accounts/{account_id}")
async def api_remove_account(account_id: int, request: Request,
                             user_data=Depends(get_current_user), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.mobile == user_data["sub"]).first()
    if not user:
        raise HTTPException(404, "User not found")

    result = remove_user_account(db, user.id, account_id)
    if not result["success"]:
        raise HTTPException(400, result["reason"])

    primary = get_primary_account(db, user.id)
    if primary:
        user.bank_id = primary.bank_id
        user.account_id = primary.account_id
    else:
        user.bank_id = None
        user.account_id = None
    db.commit()

    ip = _client_ip(request)
    log_audit(db, "ACCOUNT_REMOVED", user.mobile, f"account_record={account_id}", ip_address=ip)
    return result


@app.get("/api/ifsc/{ifsc_code}")
async def api_lookup_ifsc(ifsc_code: str, db: Session = Depends(get_db)):
    result = lookup_by_ifsc(db, ifsc_code)
    if not result:
        raise HTTPException(404, "IFSC code not found")
    return result


@app.post("/api/banks/self-register")
async def api_self_register_bank(req: BankSelfRegisterRequest, request: Request,
                                 db: Session = Depends(get_db)):
    result = register_bank(db, {
        "bank_id": req.bank_id,
        "name": req.name,
        "short_code": req.short_code,
        "api_url": req.api_url,
        "contact_email": req.contact_email,
        "contact_name": req.contact_name,
        "environment": req.environment or "sandbox",
    }, admin_mobile="self-registration")

    if not result["success"]:
        raise HTTPException(400, result["reason"])

    ip = _client_ip(request)
    log_audit(db, "BANK_SELF_REGISTERED", req.contact_email,
              f"bank_id={req.bank_id} name={req.name}", ip_address=ip)

    return result


@app.get("/api/balance")
async def balance(user_data=Depends(get_current_user), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.mobile == user_data["sub"]).first()
    if not user or not user.bank_id:
        raise HTTPException(400, "Bank not linked")

    bal = await get_bank_balance(user.bank_id, user.account_id)
    bank = AVAILABLE_BANKS.get(user.bank_id, {})
    if bal is not None:
        return {
            "state": 1, "balance": bal, "account_id": user.account_id,
            "bank_name": bank.get("name", ""), "bank_label": bank.get("label", "")
        }
    raise HTTPException(503, "Balance unavailable")


@app.post("/api/pay")
async def pay(req: PayRequest, request: Request,
              user_data=Depends(get_current_user), db: Session = Depends(get_db)):
    result = await execute_payment(
        db, user_data["sub"], req.receiver_mobile.strip(),
        req.amount, req.note or "", req.idempotency_key
    )
    return result


@app.post("/api/find_user")
async def find_user(req: FindUserRequest, user_data=Depends(get_current_user), db: Session = Depends(get_db)):
    target = db.query(User).filter(User.mobile == req.mobile.strip()).first()
    if not target or not target.bank_id:
        raise HTTPException(404, "User not found or bank not linked")
    bank = AVAILABLE_BANKS.get(target.bank_id, {})
    return {"state": 1, "name": target.name, "mobile": target.mobile, "bank": bank.get("name", "")}


@app.get("/api/history")
async def history(user_data=Depends(get_current_user), db: Session = Depends(get_db)):
    mobile = user_data["sub"]
    txns = db.query(Transaction).filter(
        (Transaction.sender_mobile == mobile) | (Transaction.receiver_mobile == mobile)
    ).order_by(desc(Transaction.created_at)).limit(50).all()
    return [{
        "tx_id": t.tx_id, "state": t.state, "amount": t.amount,
        "sender_mobile": t.sender_mobile, "receiver_mobile": t.receiver_mobile,
        "sender_name": t.sender_name, "receiver_name": t.receiver_name,
        "note": t.note, "transit_ms": t.transit_time_ms,
        "reason": t.reason, "signature": t.signature,
        "time": t.created_at.strftime("%H:%M:%S") if t.created_at else "",
        "date": t.created_at.strftime("%d %b %Y") if t.created_at else "",
        "fraud_score": t.fraud_score,
    } for t in txns]


@app.post("/api/kyc/submit")
async def kyc_submit(req: KYCSubmitRequest, user_data=Depends(get_current_user), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.mobile == user_data["sub"]).first()
    if not user:
        raise HTTPException(404, "User not found")
    result = submit_kyc_document(db, user.id, req.document_type.upper(), req.document_number.strip())
    if not result["success"]:
        raise HTTPException(400, result["reason"])
    return result


@app.get("/api/kyc/status")
async def kyc_status(user_data=Depends(get_current_user), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.mobile == user_data["sub"]).first()
    if not user:
        raise HTTPException(404, "User not found")
    records = db.query(KYCRecord).filter(KYCRecord.user_id == user.id).all()
    return {
        "kyc_level": user.kyc_level,
        "kyc_status": user.kyc_status,
        "documents": [{
            "id": r.id, "type": r.document_type,
            "number": r.document_number[:4] + "****",
            "status": r.verification_status,
            "verified_at": r.verified_at.isoformat() if r.verified_at else None
        } for r in records]
    }


@app.get("/api/admin/metrics")
async def admin_metrics(user_data=Depends(get_current_user), db: Session = Depends(get_db)):
    require_admin(user_data, db)
    return get_system_metrics(db)


@app.get("/api/admin/users")
async def admin_users(user_data=Depends(get_current_user), db: Session = Depends(get_db)):
    require_admin(user_data, db)
    users = db.query(User).order_by(desc(User.created_at)).limit(100).all()
    return [{
        "id": u.id, "name": u.name, "mobile": u.mobile, "email": u.email,
        "kyc_level": u.kyc_level, "kyc_status": u.kyc_status,
        "bank_id": u.bank_id, "account_id": u.account_id,
        "role": u.role, "is_active": u.is_active,
        "created_at": u.created_at.isoformat() if u.created_at else None
    } for u in users]


@app.get("/api/admin/transactions")
async def admin_transactions(user_data=Depends(get_current_user), db: Session = Depends(get_db)):
    require_admin(user_data, db)
    txns = db.query(Transaction).order_by(desc(Transaction.created_at)).limit(100).all()
    return [{
        "tx_id": t.tx_id, "state": t.state, "amount": t.amount,
        "sender_name": t.sender_name, "receiver_name": t.receiver_name,
        "sender_mobile": t.sender_mobile, "receiver_mobile": t.receiver_mobile,
        "transit_ms": t.transit_time_ms, "reason": t.reason,
        "fraud_score": t.fraud_score, "signature": t.signature,
        "created_at": t.created_at.isoformat() if t.created_at else None
    } for t in txns]


@app.get("/api/admin/bank_accounts")
async def admin_bank_accounts(user_data=Depends(get_current_user), db: Session = Depends(get_db)):
    require_admin(user_data, db)
    return get_all_bank_accounts()


@app.get("/api/admin/bank_logs/{bank_id}")
async def admin_bank_logs(bank_id: str, user_data=Depends(get_current_user), db: Session = Depends(get_db)):
    require_admin(user_data, db)
    return get_bank_logs(bank_id)


@app.get("/api/compliance/aml_alerts")
async def aml_alerts(user_data=Depends(get_current_user), db: Session = Depends(get_db)):
    require_admin(user_data, db)
    alerts = db.query(AMLAlert).order_by(desc(AMLAlert.created_at)).limit(100).all()
    return [{
        "id": a.id, "user_id": a.user_id, "tx_id": a.tx_id,
        "risk_score": a.risk_score, "reason": a.reason,
        "status": a.status,
        "created_at": a.created_at.isoformat() if a.created_at else None
    } for a in alerts]


@app.post("/api/compliance/aml_action")
async def aml_action(req: AMLActionRequest, request: Request,
                     user_data=Depends(get_current_user), db: Session = Depends(get_db)):
    require_admin(user_data, db)
    alert = db.query(AMLAlert).filter(AMLAlert.id == req.alert_id).first()
    if not alert:
        raise HTTPException(404, "Alert not found")
    alert.status = req.action
    db.commit()
    ip = _client_ip(request)
    log_audit(db, "AML_ACTION", user_data["sub"], f"alert={req.alert_id} action={req.action}", ip_address=ip)
    return {"success": True, "status": alert.status}


@app.get("/api/compliance/fraud_flags")
async def fraud_flags(user_data=Depends(get_current_user), db: Session = Depends(get_db)):
    require_admin(user_data, db)
    flags = db.query(FraudFlag).order_by(desc(FraudFlag.created_at)).limit(100).all()
    return [{
        "id": f.id, "user_id": f.user_id, "tx_id": f.tx_id,
        "risk_score": f.risk_score, "flag_type": f.flag_type,
        "created_at": f.created_at.isoformat() if f.created_at else None
    } for f in flags]


@app.get("/api/compliance/kyc_records")
async def kyc_records(user_data=Depends(get_current_user), db: Session = Depends(get_db)):
    require_admin(user_data, db)
    records = db.query(KYCRecord).order_by(desc(KYCRecord.created_at)).limit(100).all()
    return [{
        "id": r.id, "user_id": r.user_id, "document_type": r.document_type,
        "document_number": r.document_number[:4] + "****",
        "verification_status": r.verification_status,
        "verified_at": r.verified_at.isoformat() if r.verified_at else None,
        "created_at": r.created_at.isoformat() if r.created_at else None
    } for r in records]


@app.post("/api/compliance/kyc_verify")
async def kyc_verify(req: KYCVerifyRequest, user_data=Depends(get_current_user), db: Session = Depends(get_db)):
    require_admin(user_data, db)
    result = verify_kyc_document(db, req.record_id, req.approve)
    if not result["success"]:
        raise HTTPException(400, result["reason"])
    return result


@app.get("/api/regulatory/audit_logs")
async def audit_logs(user_data=Depends(get_current_user), db: Session = Depends(get_db)):
    require_admin(user_data, db)
    logs = db.query(AuditLog).order_by(desc(AuditLog.timestamp)).limit(200).all()
    return [{
        "id": l.id, "event_type": l.event_type, "actor": l.actor,
        "details": l.details, "ip_address": l.ip_address,
        "timestamp": l.timestamp.isoformat() if l.timestamp else None
    } for l in logs]


@app.get("/api/regulatory/reports")
async def regulatory_reports(user_data=Depends(get_current_user), db: Session = Depends(get_db)):
    require_admin(user_data, db)
    metrics = get_system_metrics(db)
    open_aml = db.query(AMLAlert).filter(AMLAlert.status == "open").count()
    total_aml = db.query(AMLAlert).count()
    kyc_pending = db.query(KYCRecord).filter(KYCRecord.verification_status == "pending").count()
    return {
        "report_type": "RBI_SANDBOX_COMPLIANCE",
        "generated_at": datetime.utcnow().isoformat(),
        "metrics": metrics,
        "aml_summary": {"open_alerts": open_aml, "total_alerts": total_aml},
        "kyc_summary": {"pending_verifications": kyc_pending},
        "compliance_status": "COMPLIANT" if open_aml == 0 else "REVIEW_REQUIRED"
    }


@app.get("/api/regulatory/transactions")
async def regulatory_transactions(user_data=Depends(get_current_user), db: Session = Depends(get_db)):
    require_admin(user_data, db)
    txns = db.query(Transaction).order_by(desc(Transaction.created_at)).limit(500).all()
    return [{
        "tx_id": t.tx_id, "state": t.state, "amount": t.amount,
        "currency": t.currency, "sender_mobile": t.sender_mobile,
        "receiver_mobile": t.receiver_mobile, "transit_time_ms": t.transit_time_ms,
        "fraud_score": t.fraud_score, "signature": t.signature,
        "created_at": t.created_at.isoformat() if t.created_at else None
    } for t in txns]


@app.post("/api/admin/banks/register")
async def api_register_bank(req: BankRegisterRequest, request: Request,
                            user_data=Depends(get_current_user), db: Session = Depends(get_db)):
    require_admin(user_data, db)
    result = register_bank(db, {
        "bank_id": req.bank_id,
        "name": req.name,
        "short_code": req.short_code,
        "api_url": req.api_url,
        "public_key": req.public_key,
        "contact_email": req.contact_email,
        "contact_name": req.contact_name,
        "environment": req.environment or "sandbox",
        "icon": req.icon,
        "color": req.color,
    }, admin_mobile=user_data["sub"])
    if not result["success"]:
        raise HTTPException(400, result["reason"])
    return result


@app.post("/api/admin/banks/approve")
async def api_approve_bank(req: BankActionRequest, request: Request,
                           user_data=Depends(get_current_user), db: Session = Depends(get_db)):
    require_admin(user_data, db)
    result = approve_bank(db, req.bank_id, user_data["sub"])
    if not result["success"]:
        raise HTTPException(400, result["reason"])
    return result


@app.post("/api/admin/banks/suspend")
async def api_suspend_bank(req: BankActionRequest, request: Request,
                           user_data=Depends(get_current_user), db: Session = Depends(get_db)):
    require_admin(user_data, db)
    result = suspend_bank(db, req.bank_id, user_data["sub"], req.reason or "")
    if not result["success"]:
        raise HTTPException(400, result["reason"])
    return result


@app.post("/api/admin/banks/regenerate_key")
async def api_regenerate_key(req: BankActionRequest, request: Request,
                             user_data=Depends(get_current_user), db: Session = Depends(get_db)):
    require_admin(user_data, db)
    result = regenerate_api_key(db, req.bank_id, user_data["sub"])
    if not result["success"]:
        raise HTTPException(400, result["reason"])
    return result


@app.post("/api/admin/banks/health_check")
async def api_bank_health_check(req: BankActionRequest,
                                user_data=Depends(get_current_user), db: Session = Depends(get_db)):
    require_admin(user_data, db)
    result = await health_check_bank(db, req.bank_id)
    if not result["success"]:
        raise HTTPException(400, result["reason"])
    return result


@app.post("/api/admin/banks/test")
async def api_test_bank(req: BankActionRequest,
                        user_data=Depends(get_current_user), db: Session = Depends(get_db)):
    require_admin(user_data, db)
    result = await test_bank_connection(db, req.bank_id)
    if not result["success"]:
        raise HTTPException(400, result["reason"])
    return result


@app.get("/api/admin/banks/registered")
async def api_registered_banks(user_data=Depends(get_current_user), db: Session = Depends(get_db)):
    require_admin(user_data, db)
    return get_all_registered_banks(db)


@app.post("/api/admin/banks/{bank_id}/branches")
async def api_add_branch(bank_id: str, req: BranchRegisterRequest,
                         user_data=Depends(get_current_user), db: Session = Depends(get_db)):
    require_admin(user_data, db)
    result = register_branch(db, bank_id, {
        "branch_name": req.branch_name,
        "ifsc_code": req.ifsc_code,
        "branch_city": req.branch_city,
        "branch_state": req.branch_state,
        "branch_address": req.branch_address,
    }, actor=user_data["sub"])
    if not result["success"]:
        raise HTTPException(400, result["reason"])
    return result


@app.get("/api/admin/banks/{bank_id}/branches")
async def api_list_branches(bank_id: str, user_data=Depends(get_current_user),
                            db: Session = Depends(get_db)):
    require_admin(user_data, db)
    return get_branches_by_bank(db, bank_id)


@app.post("/api/admin/banks/{bank_id}/branches/bulk")
async def api_bulk_branches(bank_id: str, req: BranchBulkRequest,
                            user_data=Depends(get_current_user), db: Session = Depends(get_db)):
    require_admin(user_data, db)
    result = register_branches_bulk(db, bank_id, [b.model_dump() for b in req.branches], actor=user_data["sub"])
    if not result["success"]:
        raise HTTPException(400, result["reason"])
    return result


@app.post("/api/admin/seed_demo")
async def seed_demo(db: Session = Depends(get_db)):
    existing_admin = db.query(User).filter(User.role == "admin").first()
    if existing_admin:
        return {"message": "Demo data already seeded"}

    admin = User(
        name="Admin", mobile="0000000000", pin_hash=hash_pin("admin123"),
        email="admin@atomicpay.dev", role="admin", kyc_level=2, kyc_status="fully_verified",
        avatar_color="#f59e0b"
    )
    db.add(admin)

    ram = User(
        name="Ram Kumar", mobile="9876543210", pin_hash=hash_pin("1234"),
        bank_id="bank_a", account_id="RAM_001", kyc_level=2, kyc_status="fully_verified",
        avatar_color="#3b7fff"
    )
    sita = User(
        name="Sita Devi", mobile="9876543211", pin_hash=hash_pin("1234"),
        bank_id="bank_b", account_id="SITA_001", kyc_level=1, kyc_status="partially_verified",
        avatar_color="#f472b6"
    )
    arjun = User(
        name="Arjun Seth", mobile="9876543212", pin_hash=hash_pin("1234"),
        bank_id="bank_a", account_id="ARJUN_01", kyc_level=0, kyc_status="pending",
        avatar_color="#34d399"
    )
    db.add_all([ram, sita, arjun])
    db.commit()

    for u in [ram, sita, arjun]:
        if u.bank_id and u.account_id:
            add_user_account(db, u.id, {
                "bank_id": u.bank_id,
                "account_id": u.account_id,
                "account_type": "savings",
            })

    log_audit(db, "DEMO_SEEDED", "system", "Demo users and admin created")
    logger.info("Demo data seeded successfully")
    return {"message": "Demo data seeded successfully"}
