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
from app.models import Account, Base, InstallationState, PlaidItem, Transaction
from app.services.plaid_transactions import _collect_updates
from tests.conftest import csrf_headers


class FakePlaidClient:
    removed: list[str] = []
    sync_calls: list[str | None] = []
    item_error: str | None = None

    def __init__(self, _settings: Settings) -> None:
        pass

    def create_link_token(self, **_kwargs: object) -> dict[str, object]:
        return {"link_token": "link-sandbox-test"}

    def create_update_link_token(self, **kwargs: object) -> dict[str, object]:
        assert kwargs["access_token"] == "access-sandbox-secret"
        return {"link_token": "link-update-test"}

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

    def item_get(self, access_token: str) -> dict[str, object]:
        assert access_token == "access-sandbox-secret"
        error = (
            {"error_code": self.item_error, "error_type": "ITEM_ERROR"}
            if self.item_error
            else None
        )
        return {
            "item": {
                "item_id": "item-sandbox-1",
                "institution_id": "ins_109508",
                "institution_name": "First Platypus Bank",
                "error": error,
                "consent_expiration_time": "2027-08-15T12:00:00Z",
            }
        }

    def item_webhook_update(self, access_token: str, _webhook_uri: str) -> dict[str, object]:
        assert access_token == "access-sandbox-secret"
        return {"request_id": "request-webhook"}

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

    def transactions_sync(
        self, access_token: str, *, cursor: str | None = None, count: int = 500
    ) -> dict[str, object]:
        assert access_token == "access-sandbox-secret"
        assert count == 500
        self.sync_calls.append(cursor)
        accounts = [
            {
                "account_id": "acct-checking",
                "name": "Plaid Checking",
                "official_name": "Plaid Gold Checking",
                "mask": "1234",
                "type": "depository",
                "subtype": "checking",
                "balances": {
                    "current": 1325.25,
                    "available": 1275.25,
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
                    "current": 225.50,
                    "available": 774.50,
                    "limit": 1000,
                    "iso_currency_code": "USD",
                },
            },
        ]
        if cursor is None:
            return {
                "added": [
                    {
                        "transaction_id": "txn-grocery",
                        "account_id": "acct-credit",
                        "date": "2026-08-12",
                        "authorized_date": "2026-08-11",
                        "name": "FRESH MARKET 123",
                        "merchant_name": "Fresh Market",
                        "original_description": "FRESH MARKET 123 TULSA",
                        "payment_channel": "in store",
                        "amount": 42.75,
                        "pending": False,
                        "pending_transaction_id": None,
                        "personal_finance_category": {
                            "primary": "FOOD_AND_DRINK",
                            "detailed": "FOOD_AND_DRINK_GROCERIES",
                            "confidence_level": "VERY_HIGH",
                        },
                    },
                    {
                        "transaction_id": "txn-pay",
                        "account_id": "acct-checking",
                        "date": "2026-08-12",
                        "authorized_date": None,
                        "name": "PAYROLL",
                        "merchant_name": None,
                        "amount": -2200,
                        "pending": False,
                        "pending_transaction_id": None,
                        "personal_finance_category": {
                            "primary": "INCOME",
                            "detailed": "INCOME_WAGES",
                            "confidence_level": "HIGH",
                        },
                    },
                    {
                        "transaction_id": "txn-pending",
                        "account_id": "acct-credit",
                        "date": "2026-08-13",
                        "authorized_date": "2026-08-13",
                        "name": "BURGER PLACE",
                        "merchant_name": "Burger Place",
                        "amount": 19.25,
                        "pending": True,
                        "pending_transaction_id": None,
                        "personal_finance_category": {
                            "primary": "FOOD_AND_DRINK",
                            "detailed": "FOOD_AND_DRINK_FAST_FOOD",
                            "confidence_level": "HIGH",
                        },
                    },
                ],
                "modified": [],
                "removed": [],
                "accounts": accounts,
                "has_more": False,
                "next_cursor": "cursor-1",
                "transactions_update_status": "HISTORICAL_UPDATE_COMPLETE",
            }
        if cursor == "cursor-1":
            return {
                "added": [
                    {
                        "transaction_id": "txn-posted",
                        "account_id": "acct-credit",
                        "date": "2026-08-13",
                        "authorized_date": "2026-08-13",
                        "name": "BURGER PLACE",
                        "merchant_name": "Burger Place",
                        "amount": 18.75,
                        "pending": False,
                        "pending_transaction_id": "txn-pending",
                        "personal_finance_category": {
                            "primary": "FOOD_AND_DRINK",
                            "detailed": "FOOD_AND_DRINK_FAST_FOOD",
                            "confidence_level": "VERY_HIGH",
                        },
                    }
                ],
                "modified": [
                    {
                        "transaction_id": "txn-grocery",
                        "account_id": "acct-credit",
                        "date": "2026-08-12",
                        "authorized_date": "2026-08-11",
                        "name": "FRESH MARKET 123",
                        "merchant_name": "Fresh Market",
                        "amount": 40.00,
                        "pending": False,
                        "pending_transaction_id": None,
                        "personal_finance_category": {
                            "primary": "FOOD_AND_DRINK",
                            "detailed": "FOOD_AND_DRINK_GROCERIES",
                            "confidence_level": "VERY_HIGH",
                        },
                    }
                ],
                "removed": [{"transaction_id": "txn-pay"}],
                "accounts": accounts,
                "has_more": False,
                "next_cursor": "cursor-2",
                "transactions_update_status": "HISTORICAL_UPDATE_COMPLETE",
            }
        return {
            "added": [],
            "modified": [],
            "removed": [],
            "accounts": accounts,
            "has_more": False,
            "next_cursor": "cursor-3",
            "transactions_update_status": "HISTORICAL_UPDATE_COMPLETE",
        }

    def item_remove(self, access_token: str) -> dict[str, object]:
        self.removed.append(access_token)
        return {"request_id": "request-remove"}

    def sandbox_item_reset_login(self, access_token: str) -> dict[str, object]:
        assert access_token == "access-sandbox-secret"
        return {"reset_login": True, "request_id": "request-reset"}


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
    monkeypatch.setattr("app.services.plaid_transactions.PlaidClient", FakePlaidClient)
    FakePlaidClient.removed.clear()
    FakePlaidClient.sync_calls.clear()
    FakePlaidClient.item_error = None
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
    assert link.json() == {"link_token": "link-sandbox-test", "environment": "sandbox", "mode": "connect", "connection_id": None}

    exchange = client.post(
        "/api/v1/plaid/exchange",
        json={"public_token": "public-sandbox-test"},
        headers=headers,
    )
    assert exchange.status_code == 200, exchange.text
    payload = exchange.json()
    assert payload["configured"] is True
    assert payload["connections"][0]["institution"]["name"] == "First Platypus Bank"
    assert payload["connections"][0]["environment"] == "sandbox"
    assert payload["connections"][0]["environment_matches"] is True
    assert payload["connections"][0]["health"] == "healthy"
    assert payload["connections"][0]["consent_expiration_at"] is not None
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


def test_plaid_update_mode_repairs_item_and_refreshes_accounts(
    plaid_app: tuple[TestClient, Database, str],
) -> None:
    client, database, csrf = plaid_app
    headers = csrf_headers(csrf)
    exchange = client.post(
        "/api/v1/plaid/exchange",
        json={"public_token": "public-sandbox-test"},
        headers=headers,
    )
    assert exchange.status_code == 200
    connection_id = exchange.json()["connections"][0]["id"]

    with database.session_factory() as db:
        item = db.get(PlaidItem, connection_id)
        assert item is not None
        item.status = "error"
        item.last_error_code = "ITEM_LOGIN_REQUIRED"
        item.update_required = True
        item.update_reason = "ITEM_LOGIN_REQUIRED"
        db.commit()

    token = client.post(f"/api/v1/plaid/connections/{connection_id}/link-token", headers=headers)
    assert token.status_code == 200, token.text
    assert token.json() == {
        "link_token": "link-update-test",
        "environment": "sandbox",
        "mode": "update",
        "connection_id": connection_id,
    }

    refreshed = client.post(f"/api/v1/plaid/connections/{connection_id}/refresh", headers=headers)
    assert refreshed.status_code == 200, refreshed.text
    connection = refreshed.json()["connections"][0]
    assert connection["health"] == "healthy"
    assert connection["update_required"] is False
    assert connection["update_reason"] is None
    assert connection["status"] == "active"


def test_plaid_environment_mismatch_blocks_sync_and_allows_sandbox_cleanup_after_cutover(
    plaid_app: tuple[TestClient, Database, str],
) -> None:
    client, database, csrf = plaid_app
    headers = csrf_headers(csrf)
    exchange = client.post(
        "/api/v1/plaid/exchange",
        json={"public_token": "public-sandbox-test"},
        headers=headers,
    )
    connection_id = exchange.json()["connections"][0]["id"]
    settings = client.app.state.settings
    settings.plaid_env = "production"

    listed = client.get("/api/v1/plaid/connections")
    assert listed.status_code == 200
    connection = listed.json()["connections"][0]
    assert connection["environment"] == "sandbox"
    assert connection["environment_matches"] is False
    assert connection["health"] == "environment_mismatch"

    sync = client.post(f"/api/v1/plaid/connections/{connection_id}/sync", headers=headers)
    assert sync.status_code == 409
    assert sync.json()["error"]["code"] == "plaid_environment_mismatch"

    FakePlaidClient.removed.clear()
    removed = client.delete(f"/api/v1/plaid/connections/{connection_id}", headers=headers)
    assert removed.status_code == 200
    assert FakePlaidClient.removed == []
    with database.session_factory() as db:
        assert db.get(PlaidItem, connection_id) is None


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


def test_plaid_transactions_sync_imports_updates_and_reconciles_pending(
    plaid_app: tuple[TestClient, Database, str],
) -> None:
    client, database, csrf = plaid_app
    headers = csrf_headers(csrf)
    connected = client.post(
        "/api/v1/plaid/exchange",
        json={"public_token": "public-sandbox-test"},
        headers=headers,
    )
    assert connected.status_code == 200
    connection_id = connected.json()["connections"][0]["id"]

    first = client.post(f"/api/v1/plaid/connections/{connection_id}/sync", headers=headers)
    assert first.status_code == 200, first.text
    assert first.json()["added"] == 3
    assert first.json()["modified"] == 0
    assert first.json()["removed"] == 0
    assert first.json()["update_status"] == "HISTORICAL_UPDATE_COMPLETE"

    with database.session_factory() as db:
        item = db.get(PlaidItem, connection_id)
        assert item is not None
        assert item.transactions_cursor == "cursor-1"
        assert item.transactions_last_error_code is None
        grocery = db.scalar(select(Transaction).where(Transaction.external_id == "txn-grocery"))
        assert grocery is not None
        assert grocery.amount == Decimal("-42.7500")
        assert grocery.kind == "expense"
        assert grocery.category is not None and grocery.category.stable_key == "groceries"
        assert grocery.pfc_primary == "FOOD_AND_DRINK"
        assert grocery.original_description == "FRESH MARKET 123 TULSA"
        paycheck = db.scalar(select(Transaction).where(Transaction.external_id == "txn-pay"))
        assert paycheck is not None
        assert paycheck.amount == Decimal("2200.0000")
        assert paycheck.kind == "income"
        credit = db.scalar(select(Account).where(Account.external_id == "acct-credit"))
        assert credit is not None
        assert credit.current_balance == Decimal("-225.5000")

    second = client.post(f"/api/v1/plaid/connections/{connection_id}/sync", headers=headers)
    assert second.status_code == 200, second.text
    assert second.json()["added"] == 1
    assert second.json()["modified"] == 1
    assert second.json()["removed"] == 1

    with database.session_factory() as db:
        item = db.get(PlaidItem, connection_id)
        assert item is not None and item.transactions_cursor == "cursor-2"
        assert db.scalar(select(Transaction).where(Transaction.external_id == "txn-pay")) is None
        assert (
            db.scalar(select(Transaction).where(Transaction.external_id == "txn-pending")) is None
        )
        posted = db.scalar(select(Transaction).where(Transaction.external_id == "txn-posted"))
        assert posted is not None
        assert posted.pending is False
        assert posted.pending_transaction_external_id == "txn-pending"
        grocery = db.scalar(select(Transaction).where(Transaction.external_id == "txn-grocery"))
        assert grocery is not None and grocery.amount == Decimal("-40.0000")

    transactions = client.get("/api/v1/transactions?page_size=100")
    assert transactions.status_code == 200
    sources = {item["source_type"] for item in transactions.json()["items"]}
    assert sources == {"plaid"}


def test_plaid_connections_report_transaction_sync_state(
    plaid_app: tuple[TestClient, Database, str],
) -> None:
    client, _database, csrf = plaid_app
    headers = csrf_headers(csrf)
    exchange = client.post(
        "/api/v1/plaid/exchange",
        json={"public_token": "public-sandbox-test"},
        headers=headers,
    )
    connection_id = exchange.json()["connections"][0]["id"]
    synced = client.post(f"/api/v1/plaid/connections/{connection_id}/sync", headers=headers)
    assert synced.status_code == 200
    listed = client.get("/api/v1/plaid/connections")
    connection = listed.json()["connections"][0]
    assert connection["transactions_update_status"] == "HISTORICAL_UPDATE_COMPLETE"
    assert connection["transactions_last_synced_at"] is not None
    assert connection["transactions_last_error_code"] is None


def test_transactions_sync_restarts_pagination_after_mutation() -> None:
    class MutationClient:
        def __init__(self) -> None:
            self.calls: list[str | None] = []
            self.restarted = False

        def transactions_sync(
            self, _access_token: str, *, cursor: str | None = None, count: int = 500
        ) -> dict[str, object]:
            assert count == 500
            self.calls.append(cursor)
            if cursor is None and not self.restarted:
                return {
                    "added": [],
                    "modified": [],
                    "removed": [],
                    "accounts": [],
                    "has_more": True,
                    "next_cursor": "page-2",
                    "transactions_update_status": "INITIAL_UPDATE_COMPLETE",
                }
            if cursor == "page-2":
                self.restarted = True
                from app.integrations.plaid import PlaidAPIError

                raise PlaidAPIError(400, "TRANSACTIONS_SYNC_MUTATION_DURING_PAGINATION")
            return {
                "added": [],
                "modified": [],
                "removed": [],
                "accounts": [],
                "has_more": False,
                "next_cursor": "stable-cursor",
                "transactions_update_status": "HISTORICAL_UPDATE_COMPLETE",
            }

    client = MutationClient()
    result = _collect_updates(client, "access-token", None)  # type: ignore[arg-type]
    assert client.calls == [None, "page-2", None]
    assert result.next_cursor == "stable-cursor"
    assert result.update_status == "HISTORICAL_UPDATE_COMPLETE"


def test_transactions_sync_accepts_not_ready_empty_cursor() -> None:
    class NotReadyClient:
        def transactions_sync(
            self, _access_token: str, *, cursor: str | None = None, count: int = 500
        ) -> dict[str, object]:
            assert cursor is None
            assert count == 500
            return {
                "added": [],
                "modified": [],
                "removed": [],
                "accounts": [],
                "has_more": False,
                "next_cursor": "",
                "transactions_update_status": "NOT_READY",
            }

    result = _collect_updates(NotReadyClient(), "access-token", None)  # type: ignore[arg-type]
    assert result.next_cursor is None
    assert result.update_status == "NOT_READY"
    assert result.added == []


def test_transaction_sync_local_apply_is_atomic(
    plaid_app: tuple[TestClient, Database, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, database, csrf = plaid_app
    headers = csrf_headers(csrf)
    exchange = client.post(
        "/api/v1/plaid/exchange",
        json={"public_token": "public-sandbox-test"},
        headers=headers,
    )
    assert exchange.status_code == 200
    connection_id = exchange.json()["connections"][0]["id"]

    class InvalidTransactionClient:
        def __init__(self, _settings: Settings) -> None:
            pass

        def transactions_sync(
            self, _access_token: str, *, cursor: str | None = None, count: int = 500
        ) -> dict[str, object]:
            assert cursor is None
            assert count == 500
            return {
                "added": [
                    {
                        "transaction_id": "txn-invalid-account",
                        "account_id": "acct-not-connected",
                        "date": "2026-08-13",
                        "name": "INVALID",
                        "amount": 10,
                        "pending": False,
                        "personal_finance_category": {
                            "primary": "GENERAL_MERCHANDISE",
                            "detailed": "GENERAL_MERCHANDISE_OTHER_GENERAL_MERCHANDISE",
                            "confidence_level": "HIGH",
                        },
                    }
                ],
                "modified": [],
                "removed": [],
                "accounts": [
                    {
                        "account_id": "acct-checking",
                        "name": "Plaid Checking",
                        "official_name": "Plaid Gold Checking",
                        "mask": "1234",
                        "type": "depository",
                        "subtype": "checking",
                        "balances": {
                            "current": 9999,
                            "available": 9999,
                            "limit": None,
                            "iso_currency_code": "USD",
                        },
                    }
                ],
                "has_more": False,
                "next_cursor": "cursor-should-not-commit",
                "transactions_update_status": "INITIAL_UPDATE_COMPLETE",
            }

    monkeypatch.setattr("app.services.plaid_transactions.PlaidClient", InvalidTransactionClient)
    failed = client.post(f"/api/v1/plaid/connections/{connection_id}/sync", headers=headers)
    assert failed.status_code == 409
    assert failed.json()["error"]["code"] == "plaid_account_missing"

    with database.session_factory() as db:
        item = db.get(PlaidItem, connection_id)
        assert item is not None
        assert item.transactions_cursor is None
        checking = db.scalar(select(Account).where(Account.external_id == "acct-checking"))
        assert checking is not None
        assert checking.current_balance == Decimal("1250.2500")
        assert db.scalar(
            select(Transaction).where(Transaction.external_id == "txn-invalid-account")
        ) is None


def test_item_webhook_marks_reconnect_and_login_repaired() -> None:
    from app.api.plaid import _handle_item_webhook

    item = PlaidItem(
        user_id=1,
        external_id="item-webhook",
        access_token_ciphertext="ciphertext",
        access_token_nonce="nonce",
        environment="production",
        status="active",
    )
    _handle_item_webhook(
        item,
        {
            "webhook_code": "PENDING_DISCONNECT",
            "disconnect_time": "2026-09-01T12:00:00Z",
        },
    )
    assert item.update_required is True
    assert item.update_reason == "PENDING_DISCONNECT"
    assert item.consent_expiration_at is not None
    assert item.last_webhook_at is not None

    _handle_item_webhook(item, {"webhook_code": "LOGIN_REPAIRED"})
    assert item.status == "active"
    assert item.last_error_code is None
    assert item.update_required is False
    assert item.update_reason is None
    assert item.sync_requested_at is not None


def test_plaid_production_readiness_reports_sandbox_items(
    plaid_app: tuple[TestClient, Database, str],
) -> None:
    from app.services.plaid import production_readiness

    client, database, csrf = plaid_app
    response = client.post(
        "/api/v1/plaid/exchange",
        json={"public_token": "public-sandbox-test"},
        headers=csrf_headers(csrf),
    )
    assert response.status_code == 200
    settings = client.app.state.settings
    settings.plaid_env = "production"
    settings.plaid_redirect_uri = "https://budget.example.test/plaid/oauth"
    settings.plaid_webhook_uri = "https://budget.example.test/api/v1/plaid/webhook"
    with database.session_factory() as db:
        readiness = production_readiness(db, settings)
    assert readiness["ready"] is False
    assert readiness["sandbox_connections"] == 1
    assert any("cannot be migrated" in issue for issue in readiness["issues"])


def test_sandbox_reset_login_marks_connection_for_update_mode(
    plaid_app: tuple[TestClient, Database, str],
) -> None:
    from app.services.plaid import sandbox_reset_login

    client, database, csrf = plaid_app
    response = client.post(
        "/api/v1/plaid/exchange",
        json={"public_token": "public-sandbox-test"},
        headers=csrf_headers(csrf),
    )
    assert response.status_code == 200
    connection_id = response.json()["connections"][0]["id"]
    with database.session_factory() as db:
        result = sandbox_reset_login(db, client.app.state.settings, connection_id)
        db.commit()
        item = db.get(PlaidItem, connection_id)
        assert item is not None
        assert item.status == "error"
        assert item.update_required is True
        assert item.update_reason == "ITEM_LOGIN_REQUIRED"
    assert result["reset_login"] is True


def test_sandbox_reset_login_auto_selects_only_connection(
    plaid_app: tuple[TestClient, Database, str],
) -> None:
    from app.services.plaid import sandbox_reset_login

    client, database, csrf = plaid_app
    response = client.post(
        "/api/v1/plaid/exchange",
        json={"public_token": "public-sandbox-test"},
        headers=csrf_headers(csrf),
    )
    assert response.status_code == 200
    connection_id = response.json()["connections"][0]["id"]
    with database.session_factory() as db:
        result = sandbox_reset_login(db, client.app.state.settings)
        db.commit()
    assert result["connection_id"] == connection_id
    assert result["reset_login"] is True


def test_failed_update_refresh_commits_provider_attention_state(
    plaid_app: tuple[TestClient, Database, str],
) -> None:
    client, database, csrf = plaid_app
    headers = csrf_headers(csrf)
    exchange = client.post(
        "/api/v1/plaid/exchange",
        json={"public_token": "public-sandbox-test"},
        headers=headers,
    )
    assert exchange.status_code == 200
    connection_id = exchange.json()["connections"][0]["id"]

    FakePlaidClient.item_error = "ITEM_LOGIN_REQUIRED"
    failed = client.post(f"/api/v1/plaid/connections/{connection_id}/refresh", headers=headers)
    assert failed.status_code == 409
    assert failed.json()["error"]["code"] == "plaid_update_incomplete"

    with database.session_factory() as db:
        item = db.get(PlaidItem, connection_id)
        assert item is not None
        assert item.status == "error"
        assert item.update_required is True
        assert item.update_reason == "ITEM_LOGIN_REQUIRED"
