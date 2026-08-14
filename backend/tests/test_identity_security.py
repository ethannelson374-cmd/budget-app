from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import Settings
from app.core.database import Database
from app.core.totp import totp_code
from app.integrations.google_oidc import GoogleIdentity
from app.main import create_app
from app.models import AuthIdentity, PasswordResetToken, SessionRecord, User
from tests.conftest import csrf_headers


def test_invite_only_local_account_creation_and_admin_scope(
    authenticated: tuple[TestClient, str], database: Database
) -> None:
    client, csrf = authenticated
    security = client.get("/api/v1/auth/security")
    assert security.status_code == 200
    assert security.json()["is_admin"] is True
    assert security.json()["invite_only"] is True

    created = client.post(
        "/api/v1/auth/admin/invitations",
        headers=csrf_headers(csrf),
        json={"email": "family@example.com"},
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["delivery"] == "manual"
    invite_url = body["invite_url"]
    assert isinstance(invite_url, str)
    token = parse_qs(urlparse(invite_url).query)["token"][0]

    detail = client.get(f"/api/v1/auth/invitations/{token}")
    assert detail.status_code == 200
    assert detail.json()["email"] == "family@example.com"

    accepted = client.post(
        "/api/v1/auth/invitations/accept",
        json={"token": token, "username": "family", "password": "Family Password 123!"},
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["user"]["is_admin"] is False
    assert accepted.json()["user"]["email_verified"] is True

    # The newly signed-in non-admin cannot manage family invitations.
    denied = client.get("/api/v1/auth/admin/invitations")
    assert denied.status_code == 403


def test_password_reset_is_non_enumerating_and_admin_can_issue_manual_link(
    authenticated: tuple[TestClient, str], database: Database
) -> None:
    client, csrf = authenticated
    unknown = client.post("/api/v1/auth/password/forgot", json={"identity": "missing@example.com"})
    known = client.post("/api/v1/auth/password/forgot", json={"identity": "owner@example.com"})
    assert unknown.status_code == known.status_code == 200
    assert unknown.json() == known.json() == {"ok": True}

    users = client.get("/api/v1/auth/admin/users").json()["users"]
    owner_id = next(item["id"] for item in users if item["username"] == "owner")
    reset = client.post(
        f"/api/v1/auth/admin/users/{owner_id}/password-reset",
        headers=csrf_headers(csrf),
    )
    assert reset.status_code == 200, reset.text
    assert reset.json()["delivery"] == "manual"
    reset_url = reset.json()["reset_url"]
    token = parse_qs(urlparse(reset_url).query)["token"][0]

    status = client.get("/api/v1/auth/password/reset", params={"token": token})
    assert status.json() == {"valid": True, "email": "owner@example.com"}
    completed = client.post(
        "/api/v1/auth/password/reset",
        json={"token": token, "password": "A New Owner Password 456!"},
    )
    assert completed.status_code == 200
    assert client.get("/api/v1/auth/me").status_code == 401

    login = client.post(
        "/api/v1/auth/login",
        json={"identity": "owner", "password": "A New Owner Password 456!"},
    )
    assert login.status_code == 200
    assert login.json()["authenticated"] is True
    with database.session_factory() as db:
        assert db.scalar(select(PasswordResetToken).where(PasswordResetToken.used_at.is_not(None))) is not None


def test_session_management_tracks_user_agent_and_revokes_other_session(
    authenticated: tuple[TestClient, str], database: Database
) -> None:
    client, csrf = authenticated
    # Establish a second session in an independent cookie jar.
    with TestClient(client.app) as other:
        logged = other.post(
            "/api/v1/auth/login",
            headers={"User-Agent": "Mozilla/5.0 Windows Edg/151"},
            json={"identity": "owner", "password": "Correct Horse Battery Staple!"},
        )
        assert logged.status_code == 200
        assert logged.json()["authenticated"] is True
        sessions = client.get("/api/v1/auth/sessions").json()["sessions"]
        assert len(sessions) == 2
        remote = next(item for item in sessions if not item["current"])
        assert "Edg/151" in remote["user_agent"]
        revoked = client.delete(
            f"/api/v1/auth/sessions/{remote['id']}", headers=csrf_headers(csrf)
        )
        assert revoked.status_code == 200
        assert other.get("/api/v1/auth/me").status_code == 401


def test_totp_enable_password_login_challenge_and_recovery_code(
    authenticated: tuple[TestClient, str], database: Database
) -> None:
    client, csrf = authenticated
    started = client.post("/api/v1/auth/totp/setup", headers=csrf_headers(csrf))
    assert started.status_code == 200, started.text
    secret = started.json()["secret"]
    confirmed = client.post(
        "/api/v1/auth/totp/confirm",
        headers=csrf_headers(csrf),
        json={"code": totp_code(secret)},
    )
    assert confirmed.status_code == 200, confirmed.text
    recovery = confirmed.json()["recovery_codes"][0]

    assert client.post("/api/v1/auth/logout", headers=csrf_headers(csrf)).status_code == 200
    login = client.post(
        "/api/v1/auth/login",
        json={"identity": "owner", "password": "Correct Horse Battery Staple!"},
    )
    assert login.status_code == 200
    assert login.json()["two_factor_required"] is True
    challenge = login.json()["challenge_token"]
    verified = client.post(
        "/api/v1/auth/two-factor/login",
        json={"challenge_token": challenge, "code": recovery},
    )
    assert verified.status_code == 200, verified.text
    assert client.get("/api/v1/auth/me").status_code == 200

    # A recovery code is single-use.
    assert client.post("/api/v1/auth/logout", headers=csrf_headers(verified.json()["csrf_token"])).status_code == 200
    second = client.post(
        "/api/v1/auth/login",
        json={"identity": "owner", "password": "Correct Horse Battery Staple!"},
    ).json()["challenge_token"]
    reused = client.post(
        "/api/v1/auth/two-factor/login",
        json={"challenge_token": second, "code": recovery},
    )
    assert reused.status_code == 401


def test_google_invite_creates_account_but_existing_email_requires_explicit_link(
    tmp_path, setup_payload: dict[str, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = Settings(
        _env_file=None,
        app_env="test",
        demo_mode=True,
        demo_db_path=tmp_path / "google.db",
        allowed_hosts="testserver",
        app_secret="a" * 64,
        session_secret="b" * 64,
        encryption_key="c" * 64,
        google_client_id="google-client",
        google_client_secret="google-secret",
        google_redirect_uri="http://testserver/api/v1/auth/google/callback",
    )
    from app.models import Base, InstallationState
    import app.api.security as security_api

    database = Database.from_settings(settings)
    Base.metadata.create_all(database.engine)
    with database.session_factory() as db:
        db.add(InstallationState(id=1, initialized_at=None))
        db.commit()
    try:
        with TestClient(create_app(settings, database)) as client:
            setup = client.post("/api/v1/setup", json=setup_payload)
            csrf = setup.json()["csrf_token"]
            invitation = client.post(
                "/api/v1/auth/admin/invitations",
                headers=csrf_headers(csrf),
                json={"email": "google.family@example.com"},
            ).json()
            invite_token = parse_qs(urlparse(invitation["invite_url"]).query)["token"][0]

            monkeypatch.setattr(security_api, "exchange_code", lambda _settings, _code: "id-token")

            # Start the invite flow and recover state/nonce from the authorization URL.
            started = client.get(
                "/api/v1/auth/google/start",
                params={"invite": invite_token, "return_to": "/dashboard"},
                follow_redirects=False,
            )
            auth_query = parse_qs(urlparse(started.headers["location"]).query)
            state = auth_query["state"][0]
            nonce = auth_query["nonce"][0]
            monkeypatch.setattr(
                security_api,
                "validate_id_token",
                lambda _settings, _token: GoogleIdentity(
                    subject="google-family-sub",
                    email="google.family@example.com",
                    email_verified=True,
                    name="Google Family",
                    nonce=nonce,
                ),
            )
            callback = client.get(
                "/api/v1/auth/google/callback",
                params={"state": state, "code": "code"},
                follow_redirects=False,
            )
            assert callback.status_code == 302
            assert callback.headers["location"].startswith("/auth/google/complete")
            with database.session_factory() as db:
                member = db.scalar(select(User).where(User.normalized_email == "google.family@example.com"))
                assert member is not None and member.password_hash is None
                assert db.scalar(select(AuthIdentity).where(AuthIdentity.user_id == member.id)) is not None

            # The original owner's matching email must never be silently linked.
            started = client.get("/api/v1/auth/google/start", follow_redirects=False)
            auth_query = parse_qs(urlparse(started.headers["location"]).query)
            state = auth_query["state"][0]
            nonce = auth_query["nonce"][0]
            monkeypatch.setattr(
                security_api,
                "validate_id_token",
                lambda _settings, _token: GoogleIdentity(
                    subject="different-google-sub",
                    email="owner@example.com",
                    email_verified=True,
                    name="Owner",
                    nonce=nonce,
                ),
            )
            collision = client.get(
                "/api/v1/auth/google/callback",
                params={"state": state, "code": "code"},
                follow_redirects=False,
            )
            assert "auth_error=google_link_required" in collision.headers["location"]
    finally:
        database.engine.dispose()
