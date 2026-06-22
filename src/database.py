import os

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.models import Base, URLRecord

load_dotenv()

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://urluser:urlpassword@localhost:5432/urlshortener",
)

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
    expire_on_commit=False,
)


def create_tables() -> None:
    Base.metadata.create_all(bind=engine)


def create_url(code: str, target_url: str) -> URLRecord:
    session = SessionLocal()
    try:
        record = URLRecord(code=code, target_url=target_url)
        session.add(record)
        session.commit()
        session.refresh(record)
        return record
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_by_code(code: str) -> URLRecord | None:
    session = SessionLocal()
    try:
        return session.query(URLRecord).filter(URLRecord.code == code).first()
    finally:
        session.close()


def get_by_target(target_url: str) -> URLRecord | None:
    session = SessionLocal()
    try:
        return session.query(URLRecord).filter(URLRecord.target_url == target_url).first()
    finally:
        session.close()


def increment_hits(code: str) -> URLRecord | None:
    session = SessionLocal()
    try:
        record = session.query(URLRecord).filter(URLRecord.code == code).first()
        if record is None:
            return None
        record.hit_count += 1
        session.commit()
        session.refresh(record)
        return record
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
