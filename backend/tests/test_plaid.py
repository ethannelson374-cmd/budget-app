from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from cryptography.exceptions import InvalidTag
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError
from sqlalchemy import select

from app.core.config import Settings
from app.core.database import Database
from app.core.token_crypto import decrypt_plaid_access_token, encrypt_plaid_access_token
from app.main import create_app
from app.models import Account, Base, InstallationState, PlaidItem
from tests.conftest import csrf_headers


class FakePlaidClient:
    removed: list[str] = []

    def __init__(self, _settings: Settings) -> None:
        pass

    def create_link_token(self, **_kwargs: object) -> dict[str, object]:
        return {"link_token": "link-sandbox-test"}

    def exchange_public_token(self, public_token: str) -> dict[str, object]:
        assert public_token == "public-sandbox-test"
        return {"access_token": "access-sandbox-secret", "item_id": "item-sandbox-1"}

    def accounts_get(self, access_token: str) -> dict[str, object]:
        assert access_token == "access-sandbox-secret"
        return {
            "item": {
                "item_id": "item-sandbox-1",
                "institution_id": "ins_109508",
                "institution_name": "First Platypus Bank",
            },
            "accounts": [
                {
                    "account_id": "acct-checking",
                    "name": "Plaid Checking",
                    "official_name": "Plaid Gold Checking",
                    "mask": "1234",
                    "type": "depository",
                    "subtype": "checking",
                    "balances": {
                        "current": 1250.25,
                        "available": 1200.25,
                        "limit": None,
                        "iso_currency_code": "USD",
                    },
                },
                {
                    "account_id": "acct-credit",
                    "name": "Plaid Credit",
                    "official_name": None,
                    "mask": "9876",
                    "type": "credit",
                    "subtype": "credit card",
                    "balances": {
                        "current": 200.50,
                        "available": 799.50,
                        "limit": 1000,
                        "iso_currency_code": "USD",
                    },
                },
            ],
        }

    def institution_get(self, institution_id: str, _country_codes: list[str]) -> dict[str, object]:
        assert institution_id == "ins_109508"
        return {
            "institution": {
                "name": "First Platypus Bank",
                "logo": "aW1hZ2U=",
                "primary_color": "#00A86B",
                "url": "https://example.test",
            }
        }

    def item_remove(self, access_token: str) -> dict[str, object]:
        self.removed.append(access_token)
        return {"request_id": "request-remove"}


@pytest.fixture
def plaid_app(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    setup_payload: dict[str, object],
) -> Iterator[tuple[TestClient, Database, str]]:
    settings = Settings(
        _env_file=None,
        app_env="test",
        demo_mode=True,
        demo_db_path=tmp_path / "plaid.db",
        allowed_hosts="testserver,localhost",
        app_secret="a" * 64,
        session_secret="b" * 64,
        encryption_key="c" * 64,
        plaid_client_id="plaid-client-id",
        plaid_secret="plaid-sandbox-secret",
        plaid_env="sandbox",
        plaid_redirect_uri="http://testserver/plaid/oauth",
    )
    database = Database.from_settings(settings)
    Base.metadata.create_all(database.engine)
    with database.session_factory() as db:
        db.add(InstallationState(id=1, initialized_at=None))
        db.commit()
    monkeypatch.setattr("app.services.plaid.PlaidClient", FakePlaidClient)
    FakePlaidClient.removed.clear()
    try:
        with TestClient(create_app(settings, database)) as client:
            setup = client.post("/api/v1/setup", json=setup_payload)
            assert setup.status_code == 200
            yield client, database, setup.json()["csrf_token"]
    finally:
        database.engine.dispose()


def test_plaid_settings_pair_credentials_and_require_redirect() -> None:
    with pytest.raises(ValidationError, match="configured together"):
        Settings(_env_file=None, plaid_client_id="client-only")
    with pytest.raises(ValidationError, match="PLAID_REDIRECT_URI"):
        Settings(_env_file=None, plaid_client_id="client", plaid_secret="secret")

    settings = Settings(
        _env_file=None,
        plaid_client_id="client",
        plaid_secret="secret",
        plaid_redirect_uri="http://localhost:5173/plaid/oauth",
        plaid_products=" transactions,transactions ",
        plaid_country_codes=" us ",
    )
    assert settings.plaid_configured is True
    assert settings.plaid_product_list == ["transactions"]
    assert settings.plaid_country_code_list == ["US"]
    assert "plaid-sandbox-secret" not in repr(settings)


def test_production_plaid_redirect_must_be_https() -> None:
    values: dict[str, Any] = {
        "_env_file": None,
        "app_env": "production",
        "demo_mode": False,
        "app_secret": "a" * 64,
        "session_secret": "b" * 64,
        "encryption_key": "c" * 64,
        "db_host": "mysql.internal.example",
        "db_port": 3306,
        "db_name": "budget",
        "db_user": "budgetapp",
        "db_password": "database-secret",
        "db_ssl_required": True,
        "plaid_client_id": "client",
        "plaid_secret": "secret",
        "plaid_redirect_uri": "http://budget.example.com/plaid/oauth",
    }
    with pytest.raises(ValidationError, match="must use HTTPS"):
        Settings(**values)


def test_access_token_encryption_roundtrip_and_tamper_rejection() -> None:
    secret = SecretStr("c" * 64)
    ciphertext, nonce = encrypt_plaid_access_token(
        "access-token-never-store-plain",
        secret,
        user_id=7,
        item_external_id="item-1",
    )
    assert "access-token-never-store-plain" not in ciphertext
    assert decrypt_plaid_access_token(
        ciphertext,
        nonce,
        secret,
        user_id=7,
        item_external_id="item-1",
    ) == "access-token-never-store-plain"
    with pytest.raises(InvalidTag):
        decrypt_plaid_access_token(
            ciphertext,
            nonce,
            secret,
            user_id=8,
            item_external_id="item-1",
        )


def test_plaid_link_exchange_import_list_and_disconnect(
    plaid_app: tuple[TestClient, Database, str],
) -> None:
    client, database, csrf = plaid_app
    headers = csrf_headers(csrf)

    link = client.post("/api/v1/plaid/link-token", headers=headers)
    assert link.status_code == 200
    assert link.json() == {"link_token": "link-sandbox-test", "environment": "sandbox"}

    exchange = client.post(
        "/api/v1/plaid/exchange",
        json={"public_token": "public-sandbox-test"},
        headers=headers,
    )
    assert exchange.status_code == 200, exchange.text
    payload = exchange.json()
    assert payload["configured"] is True
    assert payload["connections"][0]["institution"]["name"] == "First Platypus Bank"
    assert len(payload["connections"][0]["accounts"]) == 2

    with database.session_factory() as db:
        item = db.scalar(select(PlaidItem))
        assert item is not None
        assert item.access_token_ciphertext != "access-sandbox-secret"
        assert "access-sandbox-secret" not in item.access_token_ciphertext
        accounts = list(db.scalars(select(Account).order_by(Account.external_id)).all())
        assert {account.source_type for account in accounts} == {"plaid"}
        checking = next(account for account in accounts if account.external_id == "acct-checking")
        credit = next(account for account in accounts if account.external_id == "acct-credit")
        assert checking.current_balance == Decimal("1250.2500")
        assert credit.current_balance == Decimal("-200.5000")
        assert checking.plaid_item_id == item.id

    listed = client.get("/api/v1/plaid/connections")
    assert listed.status_code == 200
    connection_id = listed.json()["connections"][0]["id"]

    connected_account_id = listed.json()["connections"][0]["accounts"][0]["id"]
    protected = client.patch(
        f"/api/v1/accounts/{connected_account_id}",
        json={"name": "Should fail"},
        headers=headers,
    )
    assert protected.status_code == 409
    assert protected.json()["error"]["code"] == "account_managed_externally"

    removed = client.delete(f"/api/v1/plaid/connections/{connection_id}", headers=headers)
    assert removed.status_code == 200
    assert FakePlaidClient.removed == ["access-sandbox-secret"]
    with database.session_factory() as db:
        assert db.scalar(select(PlaidItem)) is None
        assert list(db.scalars(select(Account)).all()) == []


def test_duplicate_link_metadata_rejected_before_token_exchange(
    plaid_app: tuple[TestClient, Database, str],
) -> None:
    client, _database, csrf = plaid_app
    headers = csrf_headers(csrf)
    metadata = {
        "institution_id": "ins_109508",
        "accounts": [{"name": "Plaid Checking", "mask": "1234"}],
    }

    first = client.post(
        "/api/v1/plaid/exchange",
        json={"public_token": "public-sandbox-test", **metadata},
        headers=headers,
    )
    assert first.status_code == 200, first.text

    duplicate = client.post(
        "/api/v1/plaid/exchange",
        json={"public_token": "should-never-reach-plaid", **metadata},
        headers=headers,
    )
    assert duplicate.status_code == 409, duplicate.text
    assert duplicate.json()["error"]["code"] == "plaid_duplicate_item"
