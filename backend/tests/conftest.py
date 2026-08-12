from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.database import Database
from app.main import create_app
from app.models import Base, InstallationState


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        _env_file=None,
        app_env="test",
        demo_mode=True,
        demo_db_path=tmp_path / "test.db",
        allowed_hosts="testserver,localhost",
        app_secret="a" * 64,
        session_secret="b" * 64,
        encryption_key="c" * 64,
    )


@pytest.fixture
def database(settings: Settings) -> Iterator[Database]:
    database = Database.from_settings(settings)
    Base.metadata.create_all(database.engine)
    with database.session_factory() as db:
        db.add(InstallationState(id=1, initialized_at=None))
        db.commit()
    try:
        yield database
    finally:
        database.engine.dispose()


@pytest.fixture
def client(settings: Settings, database: Database) -> Iterator[TestClient]:
    with TestClient(create_app(settings, database)) as test_client:
        yield test_client


@pytest.fixture
def setup_payload() -> dict[str, object]:
    return {
        "username": "owner",
        "email": "owner@example.com",
        "password": "Correct Horse Battery Staple!",
        "currency": "USD",
        "timezone": "America/Chicago",
        "theme": "system",
        "annual_gross_income": "78000.0000",
        "pay_frequency": "biweekly",
        "category_keys": ["income", "housing", "groceries", "restaurants"],
    }


@pytest.fixture
def authenticated(client: TestClient, setup_payload: dict[str, object]) -> tuple[TestClient, str]:
    response = client.post("/api/v1/setup", json=setup_payload)
    assert response.status_code == 200, response.text
    return client, response.json()["csrf_token"]


def csrf_headers(token: str, origin: str = "http://testserver") -> dict[str, str]:
    return {"X-CSRF-Token": token, "Origin": origin}
