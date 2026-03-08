import time
import logging
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import func
from backend.models import Transaction, User, Bank, AMLAlert, FraudFlag

logger = logging.getLogger("atomicpay.monitoring")

_start_time = time.time()
_tx_counter = 0


def increment_tx_counter():
    global _tx_counter
    _tx_counter += 1


def get_system_metrics(db: Session):
    try:
        total_users = db.query(func.count(User.id)).scalar() or 0
        total_banks = 2
        total_transactions = db.query(func.count(Transaction.id)).scalar() or 0

        one_min_ago = datetime.utcnow() - timedelta(minutes=1)
        recent_tx = db.query(func.count(Transaction.id)).filter(
            Transaction.created_at >= one_min_ago
        ).scalar() or 0
        tps = recent_tx / 60.0

        avg_latency = db.query(func.avg(Transaction.transit_time_ms)).filter(
            Transaction.state == 1,
            Transaction.transit_time_ms.isnot(None)
        ).scalar() or 0

        success_count = db.query(func.count(Transaction.id)).filter(Transaction.state == 1).scalar() or 0
        total_with_attempts = db.query(func.count(Transaction.id)).scalar() or 1
        success_rate = (success_count / total_with_attempts) * 100

        open_aml = db.query(func.count(AMLAlert.id)).filter(AMLAlert.status == "open").scalar() or 0
        total_fraud_flags = db.query(func.count(FraudFlag.id)).scalar() or 0

        uptime_seconds = time.time() - _start_time

        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        today_volume = db.query(func.sum(Transaction.amount)).filter(
            Transaction.state == 1,
            Transaction.created_at >= today_start
        ).scalar() or 0

        return {
            "total_users": total_users,
            "total_banks": total_banks,
            "total_transactions": total_transactions,
            "tps": round(tps, 2),
            "avg_latency_ms": round(avg_latency, 2),
            "success_rate": round(success_rate, 2),
            "open_aml_alerts": open_aml,
            "fraud_flags": total_fraud_flags,
            "uptime_seconds": round(uptime_seconds),
            "uptime_formatted": _format_uptime(uptime_seconds),
            "today_volume": round(today_volume, 2),
            "gateway_status": "online",
            "bank_a_status": "online",
            "bank_b_status": "online",
        }
    except Exception as e:
        logger.error(f"Failed to get metrics: {e}")
        return {
            "total_users": 0, "total_banks": 2, "total_transactions": 0,
            "tps": 0, "avg_latency_ms": 0, "success_rate": 0,
            "open_aml_alerts": 0, "fraud_flags": 0,
            "uptime_seconds": round(time.time() - _start_time),
            "uptime_formatted": _format_uptime(time.time() - _start_time),
            "today_volume": 0,
            "gateway_status": "degraded", "bank_a_status": "unknown", "bank_b_status": "unknown",
        }


def _format_uptime(seconds):
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    if hours > 0:
        return f"{hours}h {minutes}m {secs}s"
    elif minutes > 0:
        return f"{minutes}m {secs}s"
    return f"{secs}s"
