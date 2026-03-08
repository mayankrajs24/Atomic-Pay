from datetime import datetime
from sqlalchemy.orm import Session
from backend.models import KYCRecord, User
from backend.compliance import log_audit
import re


def submit_kyc_document(db: Session, user_id: int, document_type: str, document_number: str):
    if document_type == "PAN":
        if not re.match(r'^[A-Z]{5}[0-9]{4}[A-Z]$', document_number.upper()):
            return {"success": False, "reason": "Invalid PAN format. Expected: ABCDE1234F"}
    elif document_type == "AADHAAR":
        cleaned = document_number.replace(" ", "")
        if not re.match(r'^\d{12}$', cleaned):
            return {"success": False, "reason": "Invalid Aadhaar format. Expected: 12 digits"}
        document_number = cleaned
    elif document_type == "PASSPORT":
        if not re.match(r'^[A-Z]\d{7}$', document_number.upper()):
            return {"success": False, "reason": "Invalid Passport format. Expected: A1234567"}
    else:
        return {"success": False, "reason": f"Unsupported document type: {document_type}"}

    existing = db.query(KYCRecord).filter(
        KYCRecord.user_id == user_id,
        KYCRecord.document_type == document_type
    ).first()
    if existing:
        existing.document_number = document_number.upper()
        existing.verification_status = "pending"
        existing.verified_at = None
    else:
        record = KYCRecord(
            user_id=user_id,
            document_type=document_type,
            document_number=document_number.upper(),
            verification_status="pending"
        )
        db.add(record)
    db.commit()

    user = db.query(User).filter(User.id == user_id).first()
    log_audit(db, "KYC_SUBMITTED", user.mobile if user else str(user_id),
              f"type={document_type}")
    return {"success": True, "message": f"{document_type} document submitted for verification"}


def verify_kyc_document(db: Session, record_id: int, approve: bool):
    record = db.query(KYCRecord).filter(KYCRecord.id == record_id).first()
    if not record:
        return {"success": False, "reason": "Record not found"}

    if approve:
        record.verification_status = "verified"
        record.verified_at = datetime.utcnow()
    else:
        record.verification_status = "rejected"

    verified_count = db.query(KYCRecord).filter(
        KYCRecord.user_id == record.user_id,
        KYCRecord.verification_status == "verified"
    ).count()

    user = db.query(User).filter(User.id == record.user_id).first()
    if user:
        if verified_count >= 2:
            user.kyc_level = 2
            user.kyc_status = "fully_verified"
        elif verified_count >= 1:
            user.kyc_level = 1
            user.kyc_status = "partially_verified"
        else:
            user.kyc_level = 0
            user.kyc_status = "pending"

    db.commit()
    log_audit(db, "KYC_VERIFIED" if approve else "KYC_REJECTED",
              "admin", f"record_id={record_id} user_id={record.user_id}")
    return {"success": True, "status": record.verification_status}
