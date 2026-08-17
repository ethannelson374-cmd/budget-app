from __future__ import annotations

from decimal import Decimal

from fastapi.testclient import TestClient

from app.core.database import Database
from tests.test_api import add_finance_data


def test_cash_flow_sankey_conserves_money_and_excludes_transfers(
    authenticated: tuple[TestClient, str], database: Database
) -> None:
    client, _ = authenticated
    add_finance_data(database)

    response = client.get("/api/v1/cash-flow?range=month&month=2026-08")
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["period"]["range"] == "month"
    assert body["period"]["label"] == "August 2026"
    assert body["summary"] == {
        "income": "3000.0000",
        "refunds": "25.0000",
        "inflow": "3025.0000",
        "spending": "1400.0000",
        "net_cash_flow": "1625.0000",
        "savings_rate": "54.1667",
        "transaction_count": 4,
        "excluded_transfer_count": 1,
    }

    incoming = sum(
        Decimal(link["amount"])
        for link in body["links"]
        if link["target"] == "cash-in"
    )
    outgoing = sum(
        Decimal(link["amount"])
        for link in body["links"]
        if link["source"] == "cash-in"
    )
    assert incoming == outgoing == Decimal("3025.0000")

    nodes = {node["id"]: node for node in body["nodes"]}
    assert nodes["retained-cash"]["amount"] == "1625.0000"
    assert nodes["category:housing"]["amount"] == "1200.0000"
    assert nodes["category:groceries"]["amount"] == "200.0000"
    assert nodes["refunds"]["amount"] == "25.0000"

    housing_link = next(link for link in body["links"] if link["target"] == "category:housing")
    assert housing_link["filters"]["kind"] == "expense"
    assert housing_link["filters"]["category_id"] is not None
    assert housing_link["share_percent"] == "39.6694"


def test_cash_flow_supports_custom_and_year_ranges(
    authenticated: tuple[TestClient, str], database: Database
) -> None:
    client, _ = authenticated
    add_finance_data(database)

    custom = client.get(
        "/api/v1/cash-flow?range=custom&start_date=2026-08-05&end_date=2026-08-06"
    )
    assert custom.status_code == 200, custom.text
    assert custom.json()["summary"]["income"] == "3000.0000"
    assert custom.json()["summary"]["spending"] == "1200.0000"
    assert custom.json()["period"]["previous_start"] == "2026-08-03"
    assert custom.json()["period"]["previous_end"] == "2026-08-04"

    yearly = client.get("/api/v1/cash-flow?range=year&year=2026")
    assert yearly.status_code == 200, yearly.text
    assert yearly.json()["period"]["start"] == "2026-01-01"
    assert yearly.json()["period"]["end"] == "2026-12-31"
    assert yearly.json()["summary"]["net_cash_flow"] == "1625.0000"


def test_cash_flow_rejects_invalid_custom_ranges(authenticated: tuple[TestClient, str]) -> None:
    client, _ = authenticated
    missing = client.get("/api/v1/cash-flow?range=custom")
    assert missing.status_code == 422
    assert missing.json()["error"]["code"] == "invalid_date_range"

    reversed_range = client.get(
        "/api/v1/cash-flow?range=custom&start_date=2026-08-20&end_date=2026-08-01"
    )
    assert reversed_range.status_code == 422
    assert reversed_range.json()["error"]["code"] == "invalid_date_range"
