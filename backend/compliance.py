import logging
from sqlalchemy.orm import Session
from backend.models import AuditLog

logger = logging.getLogger("atomicpay.compliance")


def log_audit(db: Session, event_type: str, actor: str, details: str, ip_address: str = None):
    try:
        log = AuditLog(
            event_type=event_type,
            actor=actor,
            details=details,
            ip_address=ip_address,
        )
        db.add(log)
        db.commit()
    except Exception as e:
        logger.error(f"Failed to write audit log: {e}")
        try:
            db.rollback()
        except Exception:
            pass
