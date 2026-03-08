from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, Text, ForeignKey, Index, Numeric
from sqlalchemy.sql import func
from backend.database import Base
import uuid


def gen_uuid():
    return str(uuid.uuid4())


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    mobile = Column(String(15), unique=True, nullable=False, index=True)
    email = Column(String(255), unique=True, nullable=True)
    pin_hash = Column(String(255), nullable=False)
    kyc_status = Column(String(20), default="pending")
    kyc_level = Column(Integer, default=0)
    bank_id = Column(String(50), nullable=True)
    account_id = Column(String(100), nullable=True)
    avatar_color = Column(String(10), default="#3b7fff")
    role = Column(String(20), default="user")
    is_active = Column(Boolean, default=True)
    failed_login_count = Column(Integer, default=0)
    last_failed_login = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Bank(Base):
    __tablename__ = "banks"
    id = Column(Integer, primary_key=True, autoincrement=True)
    bank_id = Column(String(50), unique=True, nullable=False)
    name = Column(String(255), nullable=False)
    short_code = Column(String(10), nullable=True)
    api_url = Column(String(500), nullable=False)
    public_key = Column(Text, nullable=True)
    contact_email = Column(String(255), nullable=True)
    icon = Column(String(10), default="\U0001f3e6")
    color = Column(String(10), default="#3b7fff")
    status = Column(String(20), default="pending")
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Transaction(Base):
    __tablename__ = "transactions"
    id = Column(Integer, primary_key=True, autoincrement=True)
    tx_id = Column(String(36), unique=True, nullable=False, default=gen_uuid, index=True)
    idempotency_key = Column(String(64), unique=True, nullable=True, index=True)
    sender_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    receiver_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    sender_mobile = Column(String(15), nullable=True)
    receiver_mobile = Column(String(15), nullable=True)
    sender_name = Column(String(255), nullable=True)
    receiver_name = Column(String(255), nullable=True)
    amount = Column(Float, nullable=False)
    currency = Column(String(5), default="INR")
    state = Column(Integer, nullable=False)
    reason = Column(String(255), nullable=True)
    signature = Column(String(64), nullable=True)
    transit_time_ms = Column(Float, nullable=True)
    note = Column(Text, nullable=True)
    fraud_score = Column(Float, default=0.0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_transactions_sender", "sender_mobile"),
        Index("ix_transactions_receiver", "receiver_mobile"),
        Index("ix_transactions_state", "state"),
        Index("ix_transactions_created", "created_at"),
        Index("ix_transactions_sender_created", "sender_mobile", "created_at"),
        Index("ix_transactions_sender_idempotency", "sender_mobile", "idempotency_key",
              unique=True, postgresql_where="idempotency_key IS NOT NULL"),
    )


class KYCRecord(Base):
    __tablename__ = "kyc_records"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    document_type = Column(String(50), nullable=False)
    document_number = Column(String(100), nullable=False)
    verification_status = Column(String(20), default="pending")
    verified_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class AMLAlert(Base):
    __tablename__ = "aml_alerts"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    tx_id = Column(String(36), nullable=True)
    risk_score = Column(Float, nullable=False)
    reason = Column(Text, nullable=False)
    status = Column(String(20), default="open", index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class FraudFlag(Base):
    __tablename__ = "fraud_flags"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    tx_id = Column(String(36), nullable=True)
    risk_score = Column(Float, nullable=False)
    flag_type = Column(String(50), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    event_type = Column(String(50), nullable=False, index=True)
    actor = Column(String(255), nullable=True)
    details = Column(Text, nullable=True)
    ip_address = Column(String(50), nullable=True)
    request_id = Column(String(36), nullable=True)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_audit_timestamp", "timestamp"),
    )
