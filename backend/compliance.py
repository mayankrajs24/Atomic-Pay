from sqlalchemy.orm import Session
from backend.models import AuditLog


def log_audit(db: Session, event_type: str, actor: str, details: str, ip_address: str = None):
    log = AuditLog(
        event_type=event_type,
        actor=actor,
        details=details,
        ip_address=ip_address
    )
    db.add(log)
    db.commit()
