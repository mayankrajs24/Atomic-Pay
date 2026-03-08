from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import func


def check_aml_rules(db: Session, user, tx_result: dict):
    from backend.models import Transaction, AMLAlert
    alerts = []

    one_hour_ago = datetime.utcnow() - timedelta(hours=1)
    recent_txns = db.query(Transaction).filter(
        Transaction.sender_mobile == user.mobile,
        Transaction.state == 1,
        Transaction.created_at >= one_hour_ago
    ).all()

    structuring_amounts = [t.amount for t in recent_txns if 9000 <= t.amount <= 10000]
    if len(structuring_amounts) >= 3:
        alerts.append({
            "risk_score": 0.8,
            "reason": f"STRUCTURING: {len(structuring_amounts)} transactions between 9000-10000 in 1 hour"
        })

    if len(recent_txns) > 15:
        alerts.append({
            "risk_score": 0.7,
            "reason": f"RAPID_TRANSFERS: {len(recent_txns)} transactions in 1 hour"
        })

    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    daily_volume = db.query(func.sum(Transaction.amount)).filter(
        Transaction.sender_mobile == user.mobile,
        Transaction.state == 1,
        Transaction.created_at >= today_start
    ).scalar() or 0
    if daily_volume > 500000:
        alerts.append({
            "risk_score": 0.6,
            "reason": f"HIGH_VOLUME: Daily transaction volume Rs.{daily_volume:,.0f}"
        })

    failed_recent = db.query(func.count(Transaction.id)).filter(
        Transaction.sender_mobile == user.mobile,
        Transaction.state == -1,
        Transaction.created_at >= one_hour_ago
    ).scalar() or 0
    if failed_recent > 10:
        alerts.append({
            "risk_score": 0.5,
            "reason": f"REPEATED_FAILURES: {failed_recent} failed transactions in 1 hour"
        })

    for alert in alerts:
        aml = AMLAlert(
            user_id=user.id,
            tx_id=tx_result.get("tx_id"),
            risk_score=alert["risk_score"],
            reason=alert["reason"],
            status="open"
        )
        db.add(aml)
    if alerts:
        db.commit()

    return alerts
