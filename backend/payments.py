import uuid
import time
import hashlib
import hmac
from sqlalchemy.orm import Session
from backend.banks import AVAILABLE_BANKS, call_bank
from backend.models import Transaction, User
from backend.fraud_detection import calculate_fraud_score
from backend.aml import check_aml_rules
from backend.compliance import log_audit


async def execute_payment(db: Session, sender_mobile: str, receiver_mobile: str, amount: float, note: str = ""):
    sender = db.query(User).filter(User.mobile == sender_mobile).first()
    receiver = db.query(User).filter(User.mobile == receiver_mobile).first()

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
    if amount <= 0:
        return _fail("INVALID_AMOUNT")
    if amount > 100000 and sender.kyc_level < 2:
        return _fail("KYC_LEVEL_REQUIRED")

    sb = AVAILABLE_BANKS.get(sender.bank_id)
    rb = AVAILABLE_BANKS.get(receiver.bank_id)
    if not sb or not rb:
        return _fail("BANK_CONFIG_ERROR")

    fraud_score = calculate_fraud_score(db, sender, amount)
    if fraud_score > 0.9:
        return _fail("TRANSACTION_BLOCKED_FRAUD")

    tx_id = str(uuid.uuid4())
    t0 = time.time()
    steps = []

    steps.append(f"Tx {tx_id[:8]}  |  State: 0 (Rajas)")
    steps.append(f"From : {sender.name} ({sender.account_id}) @ {sb['name']}")
    steps.append(f"To   : {receiver.name} ({receiver.account_id}) @ {rb['name']}")
    steps.append(f"Amt  : Rs.{amount:,.2f}")
    steps.append("-" * 42)
    steps.append("Phase 1 PREPARE")
    steps.append(f"  Debit {sender.name} @ {sb['name']}...")

    debit = await call_bank(sb["url"], {
        "action": "DEBIT", "tx_id": tx_id,
        "account_id": sender.account_id, "amount": amount
    })
    elapsed = (time.time() - t0) * 1000

    if debit.get("state") != 1:
        reason = debit.get("reason", "DEBIT_FAILED")
        avail = debit.get("available")
        steps.append(f"  REJECTED: {reason}")
        if avail is not None:
            steps.append(f"  Has Rs.{avail:.0f}  Needs Rs.{amount:.0f}")
        steps.append("State: -1 (Tamas REVERSED)")
        result = _seal(tx_id, -1, amount, sender, receiver, elapsed, reason, steps, note, fraud_score)
        _save_tx(db, result, sender, receiver)
        check_aml_rules(db, sender, result)
        log_audit(db, "PAYMENT_FAILED", sender.mobile, f"tx={tx_id[:8]} reason={reason} amt={amount}")
        return result

    nsb = debit.get("new_balance")
    steps.append(f"  Confirmed. {sender.name} balance: Rs.{nsb:,.0f}")
    steps.append(f"  Credit {receiver.name} @ {rb['name']}...")

    credit = await call_bank(rb["url"], {
        "action": "CREDIT", "tx_id": tx_id,
        "account_id": receiver.account_id, "amount": amount
    })
    elapsed = (time.time() - t0) * 1000

    if credit.get("state") != 1:
        reason = credit.get("reason", "CREDIT_FAILED")
        steps.append(f"  REJECTED: {reason}")
        steps.append("  Rolling back debit...")
        await call_bank(sb["url"], {
            "action": "UNLOCK", "tx_id": tx_id,
            "account_id": sender.account_id, "amount": amount
        })
        steps.append("  Rollback complete.")
        steps.append("State: -1 (Tamas REVERSED)")
        result = _seal(tx_id, -1, amount, sender, receiver, elapsed, reason, steps, note, fraud_score)
        _save_tx(db, result, sender, receiver)
        log_audit(db, "PAYMENT_ROLLBACK", sender.mobile, f"tx={tx_id[:8]} reason={reason}")
        return result

    nrb = credit.get("new_balance")
    steps.append(f"  Confirmed. {receiver.name} balance: Rs.{nrb:,.0f}")
    elapsed = (time.time() - t0) * 1000
    steps.append("-" * 42)
    steps.append("Phase 2 COMMIT — Both banks confirmed")
    steps.append(f"Transit (Rajas 0): {elapsed:.1f}ms")
    steps.append("State: +1 (Sattva COMPLETED)")

    result = _seal(tx_id, 1, amount, sender, receiver, elapsed, "COMPLETED", steps, note, fraud_score,
                   new_sender_bal=nsb, new_receiver_bal=nrb)
    _save_tx(db, result, sender, receiver)
    check_aml_rules(db, sender, result)
    log_audit(db, "PAYMENT_COMPLETED", sender.mobile, f"tx={tx_id[:8]} amt={amount} to={receiver.mobile}")
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
    sig = hmac.new(
        b"atomicpay-production",
        f"{tx_id}|{state}|{amount}".encode(),
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


def _save_tx(db: Session, result: dict, sender, receiver):
    tx = Transaction(
        tx_id=result["tx_id"],
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
