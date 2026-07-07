"""
Pytest fixtures for dev2 test suite.

Overrides the FastAPI `get_db` dependency with an in-memory SQLite session so
tests never need Docker or a real Postgres instance.

SQLAlchemy's JSON column type maps to TEXT in SQLite — serialization still works
identically to JSONB in Postgres for our purposes.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

from dev2_delivery.database import Base, get_db
from dev2_delivery.main import app

SQLALCHEMY_TEST_URL = "sqlite:///./test_dev2.db"

_engine = create_engine(
    SQLALCHEMY_TEST_URL,
    connect_args={"check_same_thread": False},
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_engine)


@pytest.fixture(scope="function", autouse=True)
def setup_db():
    """Create all tables before each test, drop them after."""
    Base.metadata.create_all(bind=_engine)
    yield
    Base.metadata.drop_all(bind=_engine)


@pytest.fixture(scope="function")
def db_session(setup_db):
    """Yield a test DB session."""
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(scope="function")
def client(db_session):
    """
    TestClient with get_db overridden to use the test SQLite session.

    Usage in test files:
        def test_something(client):
            response = client.post("/generate", json={...})
            assert response.status_code == 200
    """
    def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
