import os

from dotenv import load_dotenv
from sqlalchemy import create_engine, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
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


def get_or_create_url(code: str, target_url: str) -> tuple[URLRecord, bool]:
    """Atomically inserts a new (code, target_url) row, or returns the
    existing row for target_url if one already exists. Relies on the
    unique index on target_url + INSERT ... ON CONFLICT DO NOTHING so
    concurrent requests for the same URL can never both "win" and create
    duplicate rows (a check-then-insert in application code can't
    guarantee that under real concurrency).

    Returns (record, created) where created is False if another request
    had already inserted this target_url first.
    """
    session = SessionLocal()
    try:
        stmt = (
            pg_insert(URLRecord)
            .values(code=code, target_url=target_url)
            .on_conflict_do_nothing(index_elements=["target_url"])
            .returning(URLRecord)
        )
        record = session.execute(stmt).scalar_one_or_none()
        if record is not None:
            session.commit()
            return record, True

        session.rollback()
        existing = session.query(URLRecord).filter(URLRecord.target_url == target_url).first()
        return existing, False
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


def increment_hits(code: str) -> URLRecord | None:
    """Atomic UPDATE ... SET hit_count = hit_count + 1, instead of
    read-modify-write in Python, so concurrent hits on the same code can't
    lose updates to each other (Postgres serializes concurrent UPDATEs on
    the same row)."""
    session = SessionLocal()
    try:
        result = session.execute(
            update(URLRecord)
            .where(URLRecord.code == code)
            .values(hit_count=URLRecord.hit_count + 1)
        )
        if result.rowcount == 0:
            session.rollback()
            return None
        session.commit()
        return session.query(URLRecord).filter(URLRecord.code == code).first()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
