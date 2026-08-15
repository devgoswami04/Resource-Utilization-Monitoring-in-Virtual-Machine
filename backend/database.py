from __future__ import annotations

from contextlib import contextmanager
import threading
import time

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import declarative_base, sessionmaker

from backend.config import settings
from backend.logger import get_logger


logger = get_logger("backend.database")

settings.database_path.parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False, "timeout": 30},
    future=True,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
Base = declarative_base()
WRITE_LOCK = threading.RLock()


@event.listens_for(engine, "connect")
def _set_sqlite_pragmas(dbapi_connection, _connection_record) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL;")
    cursor.execute("PRAGMA synchronous=NORMAL;")
    cursor.execute("PRAGMA busy_timeout=30000;")
    cursor.close()


METRIC_COLUMN_MIGRATIONS: dict[str, str] = {
    "received_at": "TEXT",
    "load_average": "REAL",
    "process_count": "INTEGER",
    "hostname": "TEXT",
    "environment": "TEXT",
    "source": "TEXT",
    "top_processes_json": "TEXT",
    "predicted_cpu": "REAL",
    "anomaly_flag": "INTEGER DEFAULT 0",
    "health_score": "REAL",
    "severity_level": "TEXT",
    "confidence_score": "REAL",
    "trend_cpu": "REAL",
    "trend_memory": "REAL",
    "trend_disk": "REAL",
    "alert_message": "TEXT",
    "recommended_action": "TEXT",
    "decision_explanation": "TEXT",
    "remediation_suggested": "INTEGER DEFAULT 0",
    "remediation_executed": "INTEGER DEFAULT 0",
    "remediation_notes": "TEXT",
    "action_taken": "TEXT",
    "action_status": "TEXT",
    "action_timestamp": "TEXT",
    "model_version": "TEXT",
    "metric_window_size": "INTEGER",
    "ingestion_status": "TEXT",
}


def _migrate_metrics_table() -> None:
    inspector = inspect(engine)
    if "metrics" not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns("metrics")}
    pending_columns = [
        (name, sql_type)
        for name, sql_type in METRIC_COLUMN_MIGRATIONS.items()
        if name not in existing_columns
    ]

    if not pending_columns:
        return

    with engine.begin() as connection:
        for name, sql_type in pending_columns:
            logger.info("Applying schema migration for metrics.%s", name)
            connection.execute(text(f"ALTER TABLE metrics ADD COLUMN {name} {sql_type}"))


def init_db() -> None:
    from backend import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _migrate_metrics_table()
    Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope():
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def is_sqlite_lock_error(exc: Exception) -> bool:
    if not isinstance(exc, OperationalError):
        return False
    message = str(exc).lower()
    return "database is locked" in message or "database table is locked" in message


def run_with_retry(operation, *, session=None, attempts: int = 4, base_delay: float = 0.1):
    for attempt in range(1, attempts + 1):
        try:
            return operation()
        except OperationalError as exc:
            if not is_sqlite_lock_error(exc) or attempt >= attempts:
                raise
            if session is not None:
                session.rollback()
            delay = base_delay * attempt
            logger.warning(
                "SQLite lock detected, retrying in %.2fs (%s/%s).",
                delay,
                attempt,
                attempts,
            )
            time.sleep(delay)
