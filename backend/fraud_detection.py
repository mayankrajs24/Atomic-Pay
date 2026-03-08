import logging
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import func

logger = logging.getLogger("atomicpay.fraud")


def calculate_fraud_score(db: Session, sender, amount: float) -> float:
    from backend.models import Transaction, FraudFlag
    score = 0.0

    try:
        one_hour_ago = datetime.utcnow() - timedelta(hours=1)
        recent_count = db.query(func.count(Transaction.id)).filter(
            Transaction.sender_mobile == sender.mobile,
            Transaction.created_at >= one_hour_ago
        ).scalar() or 0
        if recent_count > 10:
            score += 0.3
        elif recent_count > 5:
            score += 0.15

        if amount > 50000:
            score += 0.2
        elif amount > 25000:
            score += 0.1

        if sender.kyc_level == 0:
            score += 0.15

        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        daily_total = db.query(func.sum(Transaction.amount)).filter(
            Transaction.sender_mobile == sender.mobile,
            Transaction.state == 1,
            Transaction.created_at >= today_start
        ).scalar() or 0
        if daily_total + amount > 200000:
            score += 0.25

        failed_count = db.query(func.count(Transaction.id)).filter(
            Transaction.sender_mobile == sender.mobile,
            Transaction.state == -1,
            Transaction.created_at >= one_hour_ago
        ).scalar() or 0
        if failed_count > 5:
            score += 0.2

        score = min(score, 1.0)

        if score > 0.5:
            flag = FraudFlag(
                user_id=sender.id,
                risk_score=score,
                flag_type="HIGH_RISK_TRANSACTION"
            )
            db.add(flag)
            db.commit()
            logger.warning(f"Fraud flag raised: user={sender.mobile} score={score}")

    except Exception as e:
        logger.error(f"Fraud scoring error: {e}")
        return 0.0

    return score
