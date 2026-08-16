from __future__ import annotations

from sqlalchemy import select

from app.core.database import Database
from app.models import Transaction, User
from tests.conftest import csrf_headers


def test_csv_import_is_idempotent_and_exports_are_secret_free(authenticated, database: Database) -> None:
    client, csrf = authenticated
    headers = csrf_headers(csrf)
    account = client.post(
        "/api/v1/accounts",
        headers=headers,
        json={
            "name": "Archive checking",
            "official_name": None,
            "account_type": "depository",
            "account_subtype": "checking",
            "current_balance": "0",
            "available_balance": None,
            "credit_limit": None,
            "currency": "USD",
            "mask_last4": "1234",
        },
    )
    assert account.status_code == 201, account.text
    account_id = account.json()["id"]
    csv_text = "date,description,amount,merchant,category,kind,notes,external_id\n2026-08-01,Lunch,-12.50,Example Cafe,restaurants,expense,old statement,bank-row-1\n"

    first = client.post(
        "/api/v1/privacy/import-transactions",
        headers=headers,
        json={"account_id": account_id, "csv_text": csv_text},
    )
    assert first.status_code == 200, first.text
    assert first.json() == {"total_rows": 1, "imported": 1, "skipped_duplicates": 0, "errors": []}

    second = client.post(
        "/api/v1/privacy/import-transactions",
        headers=headers,
        json={"account_id": account_id, "csv_text": csv_text},
    )
    assert second.status_code == 200, second.text
    assert second.json()["imported"] == 0
    assert second.json()["skipped_duplicates"] == 1

    with database.session_factory() as db:
        rows = list(db.scalars(select(Transaction).where(Transaction.account_id == account_id)).all())
        assert len(rows) == 1
        assert rows[0].external_id and rows[0].external_id.startswith("csv:")
        assert rows[0].source_type == "manual"

    export = client.get("/api/v1/privacy/export")
    assert export.status_code == 200
    assert "attachment" in export.headers["content-disposition"]
    assert "Correct Horse Battery Staple!" not in export.text
    assert "access_token_ciphertext" not in export.text
    assert "Lunch" in export.text

    transactions = client.get("/api/v1/privacy/transactions.csv")
    assert transactions.status_code == 200
    assert "Archive checking" in transactions.text
    assert "Lunch" in transactions.text


def test_csv_import_rejects_provider_managed_account(authenticated, database: Database) -> None:
    client, csrf = authenticated
    headers = csrf_headers(csrf)
    with database.session_factory() as db:
        user = db.scalar(select(User).where(User.username == "owner"))
        assert user is not None
        from app.models import Account
        row = Account(
            user_id=user.id,
            institution_id=None,
            plaid_item_id=None,
            external_id="provider-account",
            name="Provider checking",
            official_name=None,
            account_type="depository",
            account_subtype="checking",
            source_type="plaid",
            current_balance=0,
            available_balance=None,
            credit_limit=None,
            currency="USD",
            mask_last4="9876",
            last_synced_at=None,
        )
        db.add(row)
        db.commit()
        account_id = row.id
    response = client.post(
        "/api/v1/privacy/import-transactions",
        headers=headers,
        json={"account_id": account_id, "csv_text": "date,description,amount\n2026-08-01,Test,-1.00\n"},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "csv_import_requires_manual_account"


def test_planning_names_are_private_by_default(authenticated, database: Database) -> None:
    client, csrf = authenticated
    response = client.patch(
        "/api/v1/settings",
        headers=csrf_headers(csrf),
        json={"advisor_share_planning_names": True},
    )
    assert response.status_code == 200
    assert response.json()["advisor_share_planning_names"] is True
    response = client.patch(
        "/api/v1/settings",
        headers=csrf_headers(csrf),
        json={"advisor_share_planning_names": False},
    )
    assert response.status_code == 200
    assert response.json()["advisor_share_planning_names"] is False
