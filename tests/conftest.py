"""Pytest fixtures for unit and integration testing."""

from collections.abc import AsyncGenerator, Generator
import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, configure_sqlite_engine, get_db
from app.main import create_app


@pytest.fixture(scope="session")
def engine():
    """Create in-memory SQLite database engine shared across session."""
    test_eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    configure_sqlite_engine(test_eng)
    Base.metadata.create_all(bind=test_eng)
    yield test_eng
    Base.metadata.drop_all(bind=test_eng)


@pytest.fixture
def db_session(engine) -> Generator[Session, None, None]:
    """Provide a clean database session per test function."""
    connection = engine.connect()
    transaction = connection.begin()
    testing_session_local = sessionmaker(
        autocommit=False, autoflush=False, bind=connection
    )
    session = testing_session_local()

    yield session

    session.close()
    if transaction.is_active:
        transaction.rollback()
    connection.close()


@pytest.fixture
def test_app(db_session):
    """Create a FastAPI application instance with database dependency overridden."""
    application = create_app()

    def override_get_db():
        yield db_session

    application.dependency_overrides[get_db] = override_get_db
    yield application
    application.dependency_overrides.clear()


@pytest.fixture
def client(test_app) -> Generator[TestClient, None, None]:
    """Synchronous FastAPI TestClient fixture."""
    with TestClient(test_app) as test_client:
        yield test_client


@pytest_asyncio.fixture
async def async_client(test_app) -> AsyncGenerator[AsyncClient, None]:
    """Asynchronous HTTPX client fixture."""
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac
