import uuid
import time
import hashlib
import hmac
import logging
from sqlalchemy.orm import Session
from sqlalchemy import and_
from backend.banks import AVAILABLE_BANKS, call_bank
from backend.models import Transaction, User
from backend.fraud_detection import calculate_fraud_score
from backend.aml import check_aml_rules
from backend.compliance import log_audit
from backend.config import SESSION_SECRET, MAX_PAYMENT_AMOUNT, MIN_PAYMENT_AMOUNT, DAILY_LIMIT_DEFAULT, DAILY_LIMIT_KYC2
from datetime import datetime, timedelta

logger = logging.getLogger("atomicpay.payments")


async def execute_payment(db: Session, sender_mobile: str, receiver_mobile: str,
                          amount: float, note: str = "", idempotency_key: str = None):
    if amount < MIN_PAYMENT_AMOUNT:
        return _fail(f"Minimum payment is Rs.{MIN_PAYMENT_AMOUNT:.0f}")
    if amount > MAX_PAYMENT_AMOUNT:
        return _fail(f"Maximum payment is Rs.{MAX_PAYMENT_AMOUNT:,.0f}")

    amount = round(amount, 2)

    if idempotency_key:
        existing = db.query(Transaction).filter(
            Transaction.idempotency_key == idempotency_key,
            Transaction.sender_mobile == sender_mobile
        ).first()
        if existing:
            logger.info(f"Idempotent replay: {idempotency_key} for {sender_mobile}")
            return _tx_to_result(existing)

    sender = db.query(User).filter(
        User.mobile == sender_mobile,
        User.is_active == True
    ).first()
    receiver = db.query(User).filter(
        User.mobile == receiver_mobile,
        User.is_active == True
    ).first()

    if not sender:
        return _fail("SENDER_NOT_FOUND")
    if not receiver:
        return _fail("RECEIVER_NOT_FOUND")
    if not sender.bank_id:
        return _fail("SENDER_BANK_NOT_LINKED")
    if not receiver.bank_id:
        return _fail("RECEIVER_BANK_NOT_LINKED")
    if sender.mobile == receiver.mobile:
        return _fail("CANNOT_PAY_SELF")

    daily_limit = DAILY_LIMIT_KYC2 if sender.kyc_level >= 2 else DAILY_LIMIT_DEFAULT
    if amount > 100000 and sender.kyc_level < 2:
        return _fail("KYC_LEVEL_REQUIRED")

    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    from sqlalchemy import func
    daily_total = db.query(func.coalesce(func.sum(Transaction.amount), 0)).filter(
        Transaction.sender_mobile == sender.mobile,
        Transaction.state == 1,
        Transaction.created_at >= today_start
    ).scalar()
    if daily_total + amount > daily_limit:
        return _fail(f"Daily limit exceeded. Used: Rs.{daily_total:,.0f} / Rs.{daily_limit:,.0f}")

    sb = AVAILABLE_BANKS.get(sender.bank_id)
    rb = AVAILABLE_BANKS.get(receiver.bank_id)
    if not sb or not rb:
        return _fail("BANK_CONFIG_ERROR")

    fraud_score = calculate_fraud_score(db, sender, amount)
    if fraud_score > 0.9:
        logger.warning(f"Payment blocked by fraud: sender={sender.mobile} score={fraud_score}")
        return _fail("TRANSACTION_BLOCKED_FRAUD")

    tx_id = str(uuid.uuid4())
    t0 = time.monotonic()
    steps = []

    steps.append(f"Tx {tx_id[:8]}  |  State: 0 (Rajas)")
    steps.append(f"From : {sender.name} ({sender.account_id}) @ {sb['name']}")
    steps.append(f"To   : {receiver.name} ({receiver.account_id}) @ {rb['name']}")
    steps.append(f"Amt  : Rs.{amount:,.2f}")
    steps.append("-" * 42)
    steps.append("Phase 1 PREPARE")
    steps.append(f"  Debit {sender.name} @ {sb['name']}...")

    logger.info(f"[{tx_id[:8]}] Payment initiated: {sender.mobile} -> {receiver.mobile} Rs.{amount}")

    debit = await call_bank(sb["url"], {
        "action": "DEBIT", "tx_id": tx_id,
        "account_id": sender.account_id, "amount": amount
    }, api_key=sb.get("api_key"))
    elapsed = (time.monotonic() - t0) * 1000

    if debit.get("state") != 1:
        reason = debit.get("reason", "DEBIT_FAILED")
        avail = debit.get("available")
        steps.append(f"  REJECTED: {reason}")
        if avail is not None:
            steps.append(f"  Has Rs.{avail:.0f}  Needs Rs.{amount:.0f}")
        steps.append("State: -1 (Tamas REVERSED)")
        result = _seal(tx_id, -1, amount, sender, receiver, elapsed, reason, steps, note, fraud_score)
        _save_tx(db, result, sender, receiver, idempotency_key)
        check_aml_rules(db, sender, result)
        log_audit(db, "PAYMENT_FAILED", sender.mobile, f"tx={tx_id[:8]} reason={reason} amt={amount}")
        logger.info(f"[{tx_id[:8]}] Payment failed: {reason} ({elapsed:.1f}ms)")
        return result

    nsb = debit.get("new_balance")
    steps.append(f"  Confirmed. {sender.name} balance: Rs.{nsb:,.0f}")
    steps.append(f"  Credit {receiver.name} @ {rb['name']}...")

    credit = await call_bank(rb["url"], {
        "action": "CREDIT", "tx_id": tx_id,
        "account_id": receiver.account_id, "amount": amount
    }, api_key=rb.get("api_key"))
    elapsed = (time.monotonic() - t0) * 1000

    if credit.get("state") != 1:
        reason = credit.get("reason", "CREDIT_FAILED")
        steps.append(f"  REJECTED: {reason}")
        steps.append("  Rolling back debit...")
        await call_bank(sb["url"], {
            "action": "UNLOCK", "tx_id": tx_id,
            "account_id": sender.account_id, "amount": amount
        }, api_key=sb.get("api_key"))
        steps.append("  Rollback complete.")
        steps.append("State: -1 (Tamas REVERSED)")
        result = _seal(tx_id, -1, amount, sender, receiver, elapsed, reason, steps, note, fraud_score)
        _save_tx(db, result, sender, receiver, idempotency_key)
        log_audit(db, "PAYMENT_ROLLBACK", sender.mobile, f"tx={tx_id[:8]} reason={reason}")
        logger.info(f"[{tx_id[:8]}] Payment rolled back: {reason} ({elapsed:.1f}ms)")
        return result

    nrb = credit.get("new_balance")
    steps.append(f"  Confirmed. {receiver.name} credited successfully.")
    elapsed = (time.monotonic() - t0) * 1000
    steps.append("-" * 42)
    steps.append("Phase 2 COMMIT \u2014 Both banks confirmed")
    steps.append(f"Transit (Rajas 0): {elapsed:.1f}ms")
    steps.append("State: +1 (Sattva COMPLETED)")

    result = _seal(tx_id, 1, amount, sender, receiver, elapsed, "COMPLETED", steps, note, fraud_score,
                   new_sender_bal=nsb)
    _save_tx(db, result, sender, receiver, idempotency_key)
    check_aml_rules(db, sender, result)
    log_audit(db, "PAYMENT_COMPLETED", sender.mobile, f"tx={tx_id[:8]} amt={amount} to={receiver.mobile}")
    logger.info(f"[{tx_id[:8]}] Payment completed: Rs.{amount} ({elapsed:.1f}ms)")
    return result


def _fail(reason):
    return {
        "state": -1, "reason": reason, "steps": [reason],
        "tx_id": str(uuid.uuid4()), "transit_ms": 0,
        "sender_name": "", "receiver_name": "", "amount": 0,
        "time": time.strftime("%H:%M:%S"), "date": time.strftime("%d %b %Y"),
        "signature": "", "new_sender_bal": None, "new_receiver_bal": None,
        "fraud_score": 0
    }


def _seal(tx_id, state, amount, sender, receiver, transit_ms, reason, steps, note, fraud_score,
          new_sender_bal=None, new_receiver_bal=None):
    sig_data = f"{tx_id}|{state}|{amount}|{sender.mobile}|{receiver.mobile}"
    sig = hmac.new(
        SESSION_SECRET.encode(),
        sig_data.encode(),
        hashlib.sha256
    ).hexdigest()[:16]
    return {
        "tx_id": tx_id,
        "state": state,
        "amount": amount,
        "sender_mobile": sender.mobile,
        "receiver_mobile": receiver.mobile,
        "sender_name": sender.name,
        "receiver_name": receiver.name,
        "new_sender_bal": new_sender_bal,
        "new_receiver_bal": new_receiver_bal,
        "note": note,
        "transit_ms": round(transit_ms, 2),
        "time": time.strftime("%H:%M:%S"),
        "date": time.strftime("%d %b %Y"),
        "reason": reason,
        "signature": sig,
        "steps": steps,
        "fraud_score": round(fraud_score, 3),
    }


def _save_tx(db: Session, result: dict, sender, receiver, idempotency_key=None):
    tx = Transaction(
        tx_id=result["tx_id"],
        idempotency_key=idempotency_key,
        sender_id=sender.id,
        receiver_id=receiver.id,
        sender_mobile=result["sender_mobile"],
        receiver_mobile=result["receiver_mobile"],
        sender_name=result["sender_name"],
        receiver_name=result["receiver_name"],
        amount=result["amount"],
        state=result["state"],
        reason=result["reason"],
        signature=result["signature"],
        transit_time_ms=result["transit_ms"],
        note=result["note"],
        fraud_score=result["fraud_score"],
    )
    db.add(tx)
    db.commit()


def _tx_to_result(tx: Transaction) -> dict:
    return {
        "tx_id": tx.tx_id,
        "state": tx.state,
        "amount": tx.amount,
        "sender_mobile": tx.sender_mobile,
        "receiver_mobile": tx.receiver_mobile,
        "sender_name": tx.sender_name,
        "receiver_name": tx.receiver_name,
        "new_sender_bal": None,
        "new_receiver_bal": None,
        "note": tx.note,
        "transit_ms": tx.transit_time_ms,
        "time": tx.created_at.strftime("%H:%M:%S") if tx.created_at else "",
        "date": tx.created_at.strftime("%d %b %Y") if tx.created_at else "",
        "reason": tx.reason,
        "signature": tx.signature,
        "steps": [],
        "fraud_score": tx.fraud_score,
    }
