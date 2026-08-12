from __future__ import annotations

from typing import Final, TypedDict


class CategoryDefinition(TypedDict):
    key: str
    name: str
    group: str
    icon: str
    selected_by_default: bool


def _category(key: str, name: str, group: str, icon: str) -> CategoryDefinition:
    return {
        "key": key,
        "name": name,
        "group": group,
        "icon": icon,
        "selected_by_default": True,
    }


CURRENCIES: Final = (
    {"code": "USD", "name": "US Dollar"},
    {"code": "CAD", "name": "Canadian Dollar"},
    {"code": "EUR", "name": "Euro"},
    {"code": "GBP", "name": "British Pound"},
    {"code": "AUD", "name": "Australian Dollar"},
    {"code": "JPY", "name": "Japanese Yen"},
)

PAY_FREQUENCIES: Final = (
    {"value": "weekly", "label": "Weekly"},
    {"value": "biweekly", "label": "Every two weeks"},
    {"value": "semimonthly", "label": "Twice a month"},
    {"value": "monthly", "label": "Monthly"},
    {"value": "annual", "label": "Annually"},
)

DEFAULT_CATEGORIES: Final[tuple[CategoryDefinition, ...]] = (
    _category("income", "Income", "Income", "wallet"),
    _category("housing", "Housing", "Essentials", "home"),
    _category("utilities", "Utilities", "Essentials", "bolt"),
    _category("groceries", "Groceries", "Essentials", "basket"),
    _category("restaurants", "Restaurants", "Lifestyle", "utensils"),
    _category("transportation", "Transportation", "Essentials", "car"),
    _category("gas", "Gas", "Essentials", "fuel"),
    _category("insurance", "Insurance", "Essentials", "shield"),
    _category("subscriptions", "Subscriptions", "Lifestyle", "repeat"),
    _category("shopping", "Shopping", "Lifestyle", "bag"),
    _category("entertainment", "Entertainment", "Lifestyle", "sparkles"),
    _category("healthcare", "Healthcare", "Essentials", "heart"),
    _category("debt_payments", "Debt Payments", "Financial", "credit-card"),
    _category("savings", "Savings", "Financial", "piggy-bank"),
    _category("transfers", "Transfers", "Financial", "arrows"),
    _category("other", "Other", "Other", "circle"),
)

CATEGORY_BY_KEY: Final = {item["key"]: item for item in DEFAULT_CATEGORIES}
