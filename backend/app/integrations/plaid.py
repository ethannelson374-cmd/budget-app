from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.core.config import Settings


@dataclass(slots=True)
class PlaidAPIError(Exception):
    status_code: int
    error_code: str
    request_id: str | None = None

    def __str__(self) -> str:
        suffix = f" request_id={self.request_id}" if self.request_id else ""
        return f"Plaid request failed: {self.error_code} ({self.status_code}){suffix}"


class PlaidClient:
    def __init__(self, settings: Settings, *, timeout: float = 15.0) -> None:
        if not settings.plaid_configured:
            raise ValueError("Plaid is not configured")
        assert settings.plaid_client_id is not None
        assert settings.plaid_secret is not None
        self._client_id = settings.plaid_client_id.get_secret_value()
        self._secret = settings.plaid_secret.get_secret_value()
        self._base_url = f"https://{settings.plaid_env}.plaid.com"
        self._timeout = timeout

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        request = Request(
            f"{self._base_url}{path}",
            data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "PLAID-CLIENT-ID": self._client_id,
                "PLAID-SECRET": self._secret,
                "Plaid-Version": "2020-09-14",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=self._timeout) as response:  # noqa: S310
                try:
                    result = json.loads(response.read().decode("utf-8"))
                except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                    raise PlaidAPIError(502, "PLAID_INVALID_RESPONSE") from exc
        except HTTPError as exc:
            body: dict[str, Any] = {}
            try:
                body = json.loads(exc.read().decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                pass
            raise PlaidAPIError(
                exc.code,
                str(body.get("error_code") or "PLAID_HTTP_ERROR"),
                str(body.get("request_id")) if body.get("request_id") else None,
            ) from exc
        except (URLError, TimeoutError) as exc:
            raise PlaidAPIError(503, "PLAID_UNAVAILABLE") from exc
        if not isinstance(result, dict):
            raise PlaidAPIError(502, "PLAID_INVALID_RESPONSE")
        return result

    def create_link_token(
        self,
        *,
        client_user_id: str,
        redirect_uri: str,
        products: list[str],
        country_codes: list[str],
    ) -> dict[str, Any]:
        return self._post(
            "/link/token/create",
            {
                "user": {"client_user_id": client_user_id},
                "client_name": "Budget",
                "products": products,
                "country_codes": country_codes,
                "language": "en",
                "redirect_uri": redirect_uri,
            },
        )

    def exchange_public_token(self, public_token: str) -> dict[str, Any]:
        return self._post("/item/public_token/exchange", {"public_token": public_token})

    def accounts_get(self, access_token: str) -> dict[str, Any]:
        return self._post("/accounts/get", {"access_token": access_token})

    def institution_get(self, institution_id: str, country_codes: list[str]) -> dict[str, Any]:
        return self._post(
            "/institutions/get_by_id",
            {
                "institution_id": institution_id,
                "country_codes": country_codes,
                "options": {"include_optional_metadata": True},
            },
        )

    def transactions_sync(
        self, access_token: str, *, cursor: str | None = None, count: int = 500
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "access_token": access_token,
            "count": count,
            "options": {
                "include_original_description": True,
                "personal_finance_category_version": "v2",
            },
        }
        if cursor:
            payload["cursor"] = cursor
        return self._post("/transactions/sync", payload)

    def item_remove(self, access_token: str) -> dict[str, Any]:
        return self._post("/item/remove", {"access_token": access_token})
