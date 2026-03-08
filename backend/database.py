import logging
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, declarative_base
from backend.config import DATABASE_URL

logger = logging.getLogger("atomicpay.db")

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_size=20,
    max_overflow=40,
    pool_recycle=300,
    pool_timeout=30,
    echo=False,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


@event.listens_for(engine, "connect")
def set_pg_options(dbapi_conn, connection_record):
    try:
        cursor = dbapi_conn.cursor()
        cursor.execute("SET statement_timeout = '30s'")
        cursor.execute("SET lock_timeout = '10s'")
        cursor.close()
    except Exception:
        pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db():
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables initialized")
