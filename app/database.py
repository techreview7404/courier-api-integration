"""Database setup, SQLite WAL configuration, and session management."""

from collections.abc import Generator
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    """SQLAlchemy 2.0 Declarative Base."""
    pass


def configure_sqlite_engine(target_engine: Engine) -> None:
    """Attach connection listeners to enforce SQLite WAL mode and busy timeout."""
    @event.listens_for(target_engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, connection_record):
        try:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()
        except Exception:
            # Fallback gracefully if dbapi connection does not support pragmas
            pass


def get_engine(database_url: str = settings.DATABASE_URL) -> Engine:
    """Create and configure a SQLAlchemy Engine for the application."""
    connect_args = {}
    if database_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
        connect_args["timeout"] = 30.0

    eng = create_engine(database_url, connect_args=connect_args)
    if database_url.startswith("sqlite"):
        configure_sqlite_engine(eng)
    return eng


engine = get_engine()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency for managing database sessions."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db(target_engine: Engine = engine) -> None:
    """Initialize database tables for the given engine."""
    # Ensure all models are imported before creating tables
    import app.models  # noqa: F401

    Base.metadata.create_all(bind=target_engine)
