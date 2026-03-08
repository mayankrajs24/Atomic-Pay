import hmac
import hashlib
import secrets
import logging
import time
from datetime import datetime
from sqlalchemy.orm import Session
from backend.models import Bank, BankBranch, UserBankAccount
from backend.banks import AVAILABLE_BANKS, call_bank, ping_bank
from backend.compliance import log_audit

logger = logging.getLogger("atomicpay.bank_connector")


def generate_api_key() -> str:
    return f"apk_live_{secrets.token_hex(32)}"


def generate_webhook_secret() -> str:
    return f"whsec_{secrets.token_hex(24)}"


def sign_webhook_payload(secret: str, payload: str) -> str:
    return hmac.new(
        secret.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def register_bank(db: Session, data: dict, admin_mobile: str = None) -> dict:
    existing = db.query(Bank).filter(Bank.bank_id == data["bank_id"]).first()
    if existing:
        return {"success": False, "reason": "Bank ID already registered"}

    existing_url = db.query(Bank).filter(Bank.api_url == data["api_url"]).first()
    if existing_url:
        return {"success": False, "reason": "API URL already registered to another bank"}

    api_key = generate_api_key()
    webhook_secret = generate_webhook_secret()

    bank = Bank(
        bank_id=data["bank_id"],
        name=data["name"],
        short_code=data.get("short_code", data["bank_id"][:3].upper()),
        api_url=data["api_url"],
        api_key=api_key,
        webhook_secret=webhook_secret,
        public_key=data.get("public_key"),
        contact_email=data.get("contact_email"),
        contact_name=data.get("contact_name"),
        icon=data.get("icon", "\U0001f3e6"),
        color=data.get("color", "#3b7fff"),
        environment=data.get("environment", "sandbox"),
        status="pending",
        is_simulator=data.get("is_simulator", False),
    )
    db.add(bank)
    db.commit()
    db.refresh(bank)

    log_audit(db, "BANK_REGISTERED", admin_mobile or "system",
              f"bank_id={data['bank_id']} name={data['name']} env={bank.environment}")
    logger.info(f"Bank registered: {data['bank_id']} ({data['name']}) - status=pending")

    return {
        "success": True,
        "bank_id": bank.bank_id,
        "api_key": api_key,
        "webhook_secret": webhook_secret,
        "status": bank.status,
        "message": "Bank registered successfully. Pending admin approval before it can process transactions.",
    }


def approve_bank(db: Session, bank_id: str, admin_mobile: str) -> dict:
    bank = db.query(Bank).filter(Bank.bank_id == bank_id).first()
    if not bank:
        return {"success": False, "reason": "Bank not found"}
    if bank.status == "active":
        return {"success": False, "reason": "Bank is already active"}

    bank.status = "active"
    bank.approved_by = admin_mobile
    bank.approved_at = datetime.utcnow()
    db.commit()

    _sync_bank_to_available(bank)

    log_audit(db, "BANK_APPROVED", admin_mobile, f"bank_id={bank_id}")
    logger.info(f"Bank approved: {bank_id} by {admin_mobile}")

    return {"success": True, "bank_id": bank_id, "status": "active"}


def suspend_bank(db: Session, bank_id: str, admin_mobile: str, reason: str = "") -> dict:
    bank = db.query(Bank).filter(Bank.bank_id == bank_id).first()
    if not bank:
        return {"success": False, "reason": "Bank not found"}

    bank.status = "suspended"
    bank.notes = reason
    db.commit()

    if bank_id in AVAILABLE_BANKS and not AVAILABLE_BANKS[bank_id].get("is_simulator"):
        del AVAILABLE_BANKS[bank_id]

    log_audit(db, "BANK_SUSPENDED", admin_mobile, f"bank_id={bank_id} reason={reason}")
    logger.info(f"Bank suspended: {bank_id} reason={reason}")

    return {"success": True, "bank_id": bank_id, "status": "suspended"}


def regenerate_api_key(db: Session, bank_id: str, admin_mobile: str) -> dict:
    bank = db.query(Bank).filter(Bank.bank_id == bank_id).first()
    if not bank:
        return {"success": False, "reason": "Bank not found"}

    new_key = generate_api_key()
    bank.api_key = new_key
    db.commit()

    log_audit(db, "BANK_KEY_REGENERATED", admin_mobile, f"bank_id={bank_id}")
    logger.info(f"API key regenerated for bank: {bank_id}")

    return {"success": True, "bank_id": bank_id, "api_key": new_key}


async def health_check_bank(db: Session, bank_id: str) -> dict:
    bank = db.query(Bank).filter(Bank.bank_id == bank_id).first()
    if not bank:
        return {"success": False, "reason": "Bank not found"}

    online = await ping_bank(bank.api_url)
    bank.last_health_check = datetime.utcnow()
    bank.health_status = "healthy" if online else "unreachable"
    db.commit()

    return {
        "success": True,
        "bank_id": bank_id,
        "health_status": bank.health_status,
        "api_url": bank.api_url,
        "checked_at": bank.last_health_check.isoformat(),
    }


async def test_bank_connection(db: Session, bank_id: str) -> dict:
    bank = db.query(Bank).filter(Bank.bank_id == bank_id).first()
    if not bank:
        return {"success": False, "reason": "Bank not found"}

    results = {}

    ping_ok = await ping_bank(bank.api_url)
    results["ping"] = {"passed": ping_ok, "detail": "Bank API reachable" if ping_ok else "Bank API unreachable"}

    if ping_ok:
        status_resp = await call_bank(bank.api_url, {
            "action": "STATUS", "account_id": "__TEST__"
        })
        results["status_endpoint"] = {
            "passed": status_resp.get("state") is not None,
            "detail": "STATUS action responded",
            "response": status_resp
        }

        debit_resp = await call_bank(bank.api_url, {
            "action": "DEBIT", "tx_id": "test-000", "account_id": "__TEST__", "amount": 0
        })
        results["debit_endpoint"] = {
            "passed": debit_resp.get("state") is not None,
            "detail": "DEBIT action responded",
            "response": debit_resp
        }

    all_passed = all(r.get("passed", False) for r in results.values())

    bank.last_health_check = datetime.utcnow()
    bank.health_status = "healthy" if all_passed else "degraded" if ping_ok else "unreachable"
    db.commit()

    return {
        "success": True,
        "bank_id": bank_id,
        "all_passed": all_passed,
        "tests": results,
    }


def load_active_banks_from_db(db: Session):
    active_banks = db.query(Bank).filter(Bank.status == "active").all()
    loaded = 0
    for bank in active_banks:
        if bank.bank_id not in AVAILABLE_BANKS:
            _sync_bank_to_available(bank)
            loaded += 1
    logger.info(f"Loaded {loaded} active banks from database (total available: {len(AVAILABLE_BANKS)})")


def get_all_registered_banks(db: Session) -> list:
    banks = db.query(Bank).order_by(Bank.created_at.desc()).all()
    return [{
        "id": b.id,
        "bank_id": b.bank_id,
        "name": b.name,
        "short_code": b.short_code,
        "api_url": b.api_url,
        "contact_email": b.contact_email,
        "contact_name": b.contact_name,
        "status": b.status,
        "environment": b.environment,
        "health_status": b.health_status,
        "is_simulator": b.is_simulator,
        "total_transactions": b.total_transactions,
        "total_volume": b.total_volume,
        "approved_by": b.approved_by,
        "approved_at": b.approved_at.isoformat() if b.approved_at else None,
        "last_health_check": b.last_health_check.isoformat() if b.last_health_check else None,
        "created_at": b.created_at.isoformat() if b.created_at else None,
    } for b in banks]


def _sync_bank_to_available(bank: Bank):
    AVAILABLE_BANKS[bank.bank_id] = {
        "id": bank.bank_id,
        "name": bank.name,
        "short": bank.short_code or bank.bank_id[:3].upper(),
        "label": bank.name,
        "url": bank.api_url,
        "color": bank.color or "#3b7fff",
        "icon": bank.icon or "\U0001f3e6",
        "is_simulator": bank.is_simulator,
        "api_key": bank.api_key,
    }


def register_branch(db: Session, bank_id: str, data: dict, actor: str = "system") -> dict:
    bank = db.query(Bank).filter(Bank.bank_id == bank_id).first()
    if not bank:
        return {"success": False, "reason": "Bank not found"}

    ifsc = data.get("ifsc_code", "").strip().upper()
    if len(ifsc) != 11:
        return {"success": False, "reason": "IFSC code must be exactly 11 characters"}

    existing = db.query(BankBranch).filter(BankBranch.ifsc_code == ifsc).first()
    if existing:
        return {"success": False, "reason": f"IFSC {ifsc} already registered"}

    branch = BankBranch(
        bank_id=bank_id,
        branch_name=data["branch_name"],
        ifsc_code=ifsc,
        branch_city=data.get("branch_city"),
        branch_state=data.get("branch_state"),
        branch_address=data.get("branch_address"),
    )
    db.add(branch)
    db.commit()
    db.refresh(branch)

    log_audit(db, "BRANCH_REGISTERED", actor, f"bank={bank_id} ifsc={ifsc} branch={data['branch_name']}")
    return {"success": True, "id": branch.id, "ifsc_code": ifsc, "branch_name": branch.branch_name}


def register_branches_bulk(db: Session, bank_id: str, branches: list, actor: str = "system") -> dict:
    bank = db.query(Bank).filter(Bank.bank_id == bank_id).first()
    if not bank:
        return {"success": False, "reason": "Bank not found"}

    results = []
    for b in branches:
        r = register_branch(db, bank_id, b, actor)
        results.append(r)

    added = sum(1 for r in results if r.get("success"))
    return {"success": True, "total": len(branches), "added": added, "results": results}


def get_branches_by_bank(db: Session, bank_id: str) -> list:
    branches = db.query(BankBranch).filter(
        BankBranch.bank_id == bank_id
    ).order_by(BankBranch.branch_name).all()
    return [{
        "id": b.id,
        "bank_id": b.bank_id,
        "branch_name": b.branch_name,
        "ifsc_code": b.ifsc_code,
        "branch_city": b.branch_city,
        "branch_state": b.branch_state,
        "branch_address": b.branch_address,
        "is_active": b.is_active,
        "created_at": b.created_at.isoformat() if b.created_at else None,
    } for b in branches]


def lookup_by_ifsc(db: Session, ifsc_code: str) -> dict:
    branch = db.query(BankBranch).filter(BankBranch.ifsc_code == ifsc_code.upper()).first()
    if not branch:
        return None
    bank = db.query(Bank).filter(Bank.bank_id == branch.bank_id).first()
    return {
        "ifsc_code": branch.ifsc_code,
        "branch_name": branch.branch_name,
        "branch_city": branch.branch_city,
        "branch_state": branch.branch_state,
        "bank_id": branch.bank_id,
        "bank_name": bank.name if bank else None,
    }


def add_user_account(db: Session, user_id: int, data: dict) -> dict:
    existing = db.query(UserBankAccount).filter(
        UserBankAccount.user_id == user_id,
        UserBankAccount.bank_id == data["bank_id"],
        UserBankAccount.account_id == data["account_id"],
    ).first()
    if existing:
        if existing.is_active:
            return {"success": False, "reason": "This account is already linked"}
        existing.is_active = True
        existing.branch_ifsc = data.get("branch_ifsc") or existing.branch_ifsc
        existing.account_type = data.get("account_type") or existing.account_type
        existing.account_label = data.get("account_label") or existing.account_label
        count = db.query(UserBankAccount).filter(
            UserBankAccount.user_id == user_id,
            UserBankAccount.is_active == True,
            UserBankAccount.id != existing.id,
        ).count()
        existing.is_primary = count == 0
        db.commit()
        return {"success": True, "id": existing.id, "account_id": existing.account_id,
                "bank_id": existing.bank_id, "is_primary": existing.is_primary}

    count = db.query(UserBankAccount).filter(
        UserBankAccount.user_id == user_id,
        UserBankAccount.is_active == True
    ).count()
    is_primary = count == 0

    acc = UserBankAccount(
        user_id=user_id,
        bank_id=data["bank_id"],
        branch_ifsc=data.get("branch_ifsc"),
        account_id=data["account_id"],
        account_type=data.get("account_type", "savings"),
        account_label=data.get("account_label"),
        is_primary=is_primary,
    )
    db.add(acc)
    db.commit()
    db.refresh(acc)

    return {
        "success": True,
        "id": acc.id,
        "account_id": acc.account_id,
        "bank_id": acc.bank_id,
        "is_primary": acc.is_primary,
    }


def get_user_accounts(db: Session, user_id: int) -> list:
    accounts = db.query(UserBankAccount).filter(
        UserBankAccount.user_id == user_id,
        UserBankAccount.is_active == True
    ).order_by(UserBankAccount.is_primary.desc(), UserBankAccount.linked_at).all()

    result = []
    for a in accounts:
        bank = AVAILABLE_BANKS.get(a.bank_id, {})
        branch = None
        if a.branch_ifsc:
            b = db.query(BankBranch).filter(BankBranch.ifsc_code == a.branch_ifsc).first()
            if b:
                branch = {"ifsc": b.ifsc_code, "name": b.branch_name, "city": b.branch_city}

        result.append({
            "id": a.id,
            "bank_id": a.bank_id,
            "bank_name": bank.get("name", a.bank_id),
            "branch_ifsc": a.branch_ifsc,
            "branch": branch,
            "account_id": a.account_id,
            "account_type": a.account_type,
            "account_label": a.account_label,
            "is_primary": a.is_primary,
            "linked_at": a.linked_at.isoformat() if a.linked_at else None,
        })
    return result


def set_primary_account(db: Session, user_id: int, account_id: int) -> dict:
    acc = db.query(UserBankAccount).filter(
        UserBankAccount.id == account_id,
        UserBankAccount.user_id == user_id,
        UserBankAccount.is_active == True
    ).first()
    if not acc:
        return {"success": False, "reason": "Account not found"}

    db.query(UserBankAccount).filter(
        UserBankAccount.user_id == user_id
    ).update({"is_primary": False})

    acc.is_primary = True
    db.commit()
    return {"success": True, "primary_account_id": acc.account_id, "bank_id": acc.bank_id}


def remove_user_account(db: Session, user_id: int, account_id: int) -> dict:
    acc = db.query(UserBankAccount).filter(
        UserBankAccount.id == account_id,
        UserBankAccount.user_id == user_id,
    ).first()
    if not acc:
        return {"success": False, "reason": "Account not found"}

    was_primary = acc.is_primary
    acc.is_active = False
    acc.is_primary = False
    db.commit()

    if was_primary:
        next_acc = db.query(UserBankAccount).filter(
            UserBankAccount.user_id == user_id,
            UserBankAccount.is_active == True
        ).first()
        if next_acc:
            next_acc.is_primary = True
            db.commit()

    return {"success": True}


def get_primary_account(db: Session, user_id: int) -> UserBankAccount:
    return db.query(UserBankAccount).filter(
        UserBankAccount.user_id == user_id,
        UserBankAccount.is_primary == True,
        UserBankAccount.is_active == True
    ).first()
