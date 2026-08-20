from __future__ import annotations

from urllib.parse import urlparse

from fastapi.testclient import TestClient

from app.core.totp import totp_code
from tests.conftest import csrf_headers


def _accept_invite(
    client: TestClient,
    invite_url: str,
    *,
    email: str,
    username: str,
) -> tuple[dict[str, object], str]:
    token = urlparse(invite_url).path.rsplit("/", 1)[-1]
    exchanged = client.post("/api/v1/auth/invitations/exchange", json={"token": token})
    assert exchanged.status_code == 200, exchanged.text
    accepted = client.post(
        "/api/v1/auth/invitations/accept",
        json={
            "challenge_token": exchanged.json()["challenge_token"],
            "email": email,
            "username": username,
            "password": "A Very Long Family Password 123!",
        },
    )
    assert accepted.status_code == 200, accepted.text
    return accepted.json(), exchanged.json()["invite_type"]


def test_shared_and_independent_invites_create_distinct_budget_scopes(
    authenticated: tuple[TestClient, str],
) -> None:
    client, owner_csrf = authenticated
    account = client.post(
        "/api/v1/accounts",
        headers=csrf_headers(owner_csrf),
        json={
            "name": "Household checking",
            "account_type": "depository",
            "current_balance": "2500.00",
            "currency": "USD",
        },
    )
    assert account.status_code == 201, account.text

    shared = client.post(
        "/api/v1/auth/invitations",
        headers=csrf_headers(owner_csrf),
        json={"label": "Partner", "invite_type": "shared"},
    )
    assert shared.status_code == 201, shared.text
    assert shared.json()["invite_type"] == "shared"
    assert shared.json()["budget_owner_user_id"] is not None

    member_auth, invite_type = _accept_invite(
        client,
        shared.json()["invite_url"],
        email="partner@example.com",
        username="partner",
    )
    assert invite_type == "shared"
    member_csrf = str(member_auth["csrf_token"])

    # Shared membership resolves financial APIs through the household owner.
    accounts = client.get("/api/v1/accounts")
    assert accounts.status_code == 200
    assert [item["name"] for item in accounts.json()["accounts"]] == ["Household checking"]
    family = client.get("/api/v1/auth/family").json()
    assert family["shared"] is True
    assert family["role"] == "member"
    assert family["budget_owner_username"] == "owner"
    assert {item["username"] for item in family["members"]} == {"owner", "partner"}

    # New users must finish onboarding before they can invite anybody else.
    blocked = client.post(
        "/api/v1/auth/invitations",
        headers=csrf_headers(member_csrf),
        json={"label": "Sibling", "invite_type": "independent"},
    )
    assert blocked.status_code == 403
    completed = client.post(
        "/api/v1/onboarding/complete",
        headers=csrf_headers(member_csrf),
    )
    assert completed.status_code == 200

    independent = client.post(
        "/api/v1/auth/invitations",
        headers=csrf_headers(member_csrf),
        json={"label": "Sibling", "invite_type": "independent"},
    )
    assert independent.status_code == 201, independent.text
    independent_auth, independent_type = _accept_invite(
        client,
        independent.json()["invite_url"],
        email="sibling@example.com",
        username="sibling",
    )
    assert independent_type == "independent"
    assert independent_auth["user"]["settings"]["onboarding_complete"] is False

    # Independent invitations grant app access, never the inviter's household data.
    independent_accounts = client.get("/api/v1/accounts")
    assert independent_accounts.status_code == 200
    assert independent_accounts.json()["accounts"] == []
    independent_family = client.get("/api/v1/auth/family").json()
    assert independent_family["shared"] is False
    assert independent_family["role"] == "owner"


def test_subscription_detection_summary_and_manual_status(
    authenticated: tuple[TestClient, str],
) -> None:
    client, csrf = authenticated
    categories = client.get("/api/v1/categories/selection").json()["categories"]
    subscription_category = next(item for item in categories if item["key"] == "subscriptions")
    account = client.post(
        "/api/v1/accounts",
        headers=csrf_headers(csrf),
        json={
            "name": "Rewards card",
            "account_type": "credit",
            "current_balance": "0",
            "currency": "USD",
        },
    ).json()
    for posted in ("2026-05-01", "2026-06-01", "2026-07-01"):
        response = client.post(
            "/api/v1/transactions",
            headers=csrf_headers(csrf),
            json={
                "account_id": account["id"],
                "category_id": subscription_category["id"],
                "posted_date": posted,
                "merchant": "StreamFlix",
                "description": "StreamFlix monthly",
                "amount": "-19.99",
                "kind": "expense",
                "pending": False,
            },
        )
        assert response.status_code == 201, response.text

    rebuilt = client.post("/api/v1/recurring/rebuild", headers=csrf_headers(csrf))
    assert rebuilt.status_code == 200, rebuilt.text
    stream = next(item for item in rebuilt.json()["streams"] if item["display_name"] == "StreamFlix")
    assert stream["subscription_detected"] is True
    assert stream["is_subscription"] is True

    summary = client.get("/api/v1/subscriptions")
    assert summary.status_code == 200, summary.text
    payload = summary.json()
    assert payload["active_count"] == 1
    assert payload["monthly_total"] == "19.9900"
    assert payload["annual_total"] == "239.8800"

    paused = client.patch(
        f"/api/v1/recurring/{stream['id']}/subscription",
        headers=csrf_headers(csrf),
        json={"status": "paused"},
    )
    assert paused.status_code == 200, paused.text
    assert paused.json()["active_count"] == 0
    assert paused.json()["subscriptions"][0]["status"] == "paused"

    # Reanalysis preserves the user's subscription status/override metadata.
    client.post("/api/v1/recurring/rebuild", headers=csrf_headers(csrf))
    after = client.get("/api/v1/subscriptions").json()
    assert after["subscriptions"][0]["status"] == "paused"


def test_totp_code_cannot_be_replayed_within_same_time_window(
    authenticated: tuple[TestClient, str],
) -> None:
    client, csrf = authenticated
    setup = client.post("/api/v1/auth/totp/setup", headers=csrf_headers(csrf)).json()
    code = totp_code(setup["secret"])
    confirmed = client.post(
        "/api/v1/auth/totp/confirm",
        headers=csrf_headers(csrf),
        json={"code": code},
    )
    assert confirmed.status_code == 200, confirmed.text

    assert client.post("/api/v1/auth/logout", headers=csrf_headers(csrf)).status_code == 200
    login = client.post(
        "/api/v1/auth/login",
        json={"identity": "owner", "password": "Correct Horse Battery Staple!"},
    )
    assert login.status_code == 200
    challenge = login.json()["challenge_token"]

    replay = client.post(
        "/api/v1/auth/two-factor/login",
        json={"challenge_token": challenge, "code": code},
    )
    assert replay.status_code == 401


def test_shared_member_can_leave_and_owner_can_remove_members(
    authenticated: tuple[TestClient, str],
) -> None:
    client, owner_csrf = authenticated

    def new_shared(label: str, email: str, username: str) -> tuple[str, int]:
        created = client.post(
            "/api/v1/auth/invitations",
            headers=csrf_headers(owner_csrf),
            json={"label": label, "invite_type": "shared"},
        )
        assert created.status_code == 201, created.text
        auth, _ = _accept_invite(client, created.json()["invite_url"], email=email, username=username)
        member_id = int(auth["user"]["id"])
        member_csrf = str(auth["csrf_token"])
        done = client.post("/api/v1/onboarding/complete", headers=csrf_headers(member_csrf))
        assert done.status_code == 200
        return member_csrf, member_id

    member_csrf, member_id = new_shared("Partner", "leave@example.com", "leave-member")
    left = client.post("/api/v1/auth/family/leave", headers=csrf_headers(member_csrf))
    assert left.status_code == 200, left.text
    assert left.json()["role"] == "owner"
    assert left.json()["shared"] is False

    # Return to the original owner and create another shared member to exercise removal.
    login = client.post(
        "/api/v1/auth/login",
        json={"identity": "owner", "password": "Correct Horse Battery Staple!"},
    )
    assert login.status_code == 200, login.text
    owner_csrf2 = str(login.json()["csrf_token"])
    created = client.post(
        "/api/v1/auth/invitations",
        headers=csrf_headers(owner_csrf2),
        json={"label": "Sibling", "invite_type": "shared"},
    )
    auth, _ = _accept_invite(client, created.json()["invite_url"], email="remove@example.com", username="remove-member")
    remove_id = int(auth["user"]["id"])

    login = client.post(
        "/api/v1/auth/login",
        json={"identity": "owner", "password": "Correct Horse Battery Staple!"},
    )
    owner_csrf3 = str(login.json()["csrf_token"])
    removed = client.delete(
        f"/api/v1/auth/family/members/{remove_id}",
        headers=csrf_headers(owner_csrf3),
    )
    assert removed.status_code == 200, removed.text
    assert {member["username"] for member in removed.json()["members"]} == {"owner"}
