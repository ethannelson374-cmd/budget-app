from __future__ import annotations

from urllib.parse import urlparse

from fastapi.testclient import TestClient

from tests.conftest import csrf_headers


def test_link_invitation_creates_unonboarded_user_and_progresses(
    authenticated: tuple[TestClient, str],
) -> None:
    client, admin_csrf = authenticated
    created = client.post(
        "/api/v1/auth/admin/invitations",
        headers=csrf_headers(admin_csrf),
        json={"label": "Living room iPad"},
    )
    assert created.status_code == 201, created.text
    invitation = created.json()
    assert invitation["label"] == "Living room iPad"
    assert invitation["invite_url"].startswith("http://testserver/join/")
    token = urlparse(invitation["invite_url"]).path.rsplit("/", 1)[-1]

    exchange = client.post("/api/v1/auth/invitations/exchange", json={"token": token})
    assert exchange.status_code == 200, exchange.text
    challenge = exchange.json()["challenge_token"]

    accepted = client.post(
        "/api/v1/auth/invitations/accept",
        json={
            "challenge_token": challenge,
            "email": "new.person@example.com",
            "username": "new.person",
            "password": "A Long New Password 123!",
        },
    )
    assert accepted.status_code == 200, accepted.text
    payload = accepted.json()
    assert payload["user"]["email"] == "new.person@example.com"
    assert payload["user"]["settings"]["onboarding_complete"] is False
    assert payload["user"]["settings"]["onboarding_step"] == 0
    member_csrf = payload["csrf_token"]

    status = client.get("/api/v1/onboarding")
    assert status.json() == {"complete": False, "step": 0}

    progressed = client.patch(
        "/api/v1/onboarding",
        headers=csrf_headers(member_csrf),
        json={"step": 4},
    )
    assert progressed.json() == {"complete": False, "step": 4}

    # Progress is monotonic so a stale tab cannot send the user backwards.
    stale = client.patch(
        "/api/v1/onboarding",
        headers=csrf_headers(member_csrf),
        json={"step": 2},
    )
    assert stale.json() == {"complete": False, "step": 4}

    completed = client.post(
        "/api/v1/onboarding/complete",
        headers=csrf_headers(member_csrf),
    )
    assert completed.json() == {"complete": True, "step": 6}
    me = client.get("/api/v1/auth/me").json()["user"]
    assert me["settings"]["onboarding_complete"] is True
    assert me["settings"]["onboarding_step"] == 6

    # The one-use invitation cannot be exchanged again after redemption.
    reused = client.post("/api/v1/auth/invitations/exchange", json={"token": token})
    assert reused.status_code == 404
