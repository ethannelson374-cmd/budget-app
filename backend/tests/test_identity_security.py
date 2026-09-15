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
from app.models import AuthIdentity, PasswordResetToken, User
from tests.conftest import csrf_headers


def _registration_client(tmp_path, mode: str) -> tuple[TestClient, Database]:
    settings = Settings(
        _env_file=None,
        app_env="test",
        demo_mode=True,
        demo_db_path=tmp_path / f"registration-{mode}.db",
        allowed_hosts="testserver",
        app_secret="a" * 64,
        session_secret="b" * 64,
        encryption_key="c" * 64,
        registration_mode=mode,
    )
    from app.models import Base, InstallationState

    database = Database.from_settings(settings)
    Base.metadata.create_all(database.engine)
    with database.session_factory() as db:
        db.add(InstallationState(id=1, initialized_at=None))
        db.commit()
    return TestClient(create_app(settings, database)), database


def test_open_registration_creates_independent_unonboarded_owner(
    tmp_path, setup_payload: dict[str, object]
) -> None:
    client, database = _registration_client(tmp_path, "open")
    try:
        with client:
            assert client.post("/api/v1/setup", json=setup_payload).status_code == 200
            registered = client.post(
                "/api/v1/auth/register",
                json={
                    "email": "new@example.com",
                    "username": "new-owner",
                    "password": "A Long New Password 123!",
                },
            )
            assert registered.status_code == 200, registered.text
            body = registered.json()
            assert body["user"]["settings"]["onboarding_complete"] is False
            assert body["user"]["settings"]["onboarding_step"] == 0
            assert client.get("/api/v1/onboarding").json() == {"complete": False, "step": 0}
            with database.session_factory() as db:
                user = db.scalar(select(User).where(User.normalized_email == "new@example.com"))
                assert user is not None
                from app.models import BudgetMembership

                membership = db.get(BudgetMembership, user.id)
                assert membership is not None and membership.budget_owner_user_id == user.id

            duplicate_email = client.post(
                "/api/v1/auth/register",
                json={
                    "email": "new@example.com",
                    "username": "different",
                    "password": "A Long New Password 123!",
                },
            )
            assert duplicate_email.status_code == 409
            assert duplicate_email.json()["error"]["code"] == "registration_unavailable"
            duplicate_username = client.post(
                "/api/v1/auth/register",
                json={
                    "email": "different@example.com",
                    "username": "new-owner",
                    "password": "A Long New Password 123!",
                },
            )
            assert duplicate_username.status_code == 409
            assert duplicate_username.json()["error"]["code"] == "username_exists"
    finally:
        database.engine.dispose()


@pytest.mark.parametrize("mode", ["invite_only", "disabled"])
def test_registration_is_unavailable_when_mode_is_not_open(
    tmp_path, setup_payload: dict[str, object], mode: str
) -> None:
    client, database = _registration_client(tmp_path, mode)
    try:
        with client:
            assert client.post("/api/v1/setup", json=setup_payload).status_code == 200
            response = client.post(
                "/api/v1/auth/register",
                json={
                    "email": "new@example.com",
                    "username": "new-owner",
                    "password": "A Long New Password 123!",
                },
            )
            assert response.status_code == 403
            assert response.json()["error"]["code"] == "registration_unavailable"
    finally:
        database.engine.dispose()


def test_invitation_account_creation_and_admin_scope(
    authenticated: tuple[TestClient, str], database: Database
) -> None:
    client, csrf = authenticated
    security = client.get("/api/v1/auth/security")
    assert security.status_code == 200
    assert security.json()["is_admin"] is True
    assert security.json()["registration_mode"] == "invite_only"

    created = client.post(
        "/api/v1/auth/admin/invitations",
        headers=csrf_headers(csrf),
        json={"label": "Family test"},
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["label"] == "Family test"
    invite_url = body["invite_url"]
    assert isinstance(invite_url, str)
    token = urlparse(invite_url).path.rsplit("/", 1)[-1]

    detail = client.post("/api/v1/auth/invitations/exchange", json={"token": token})
    assert detail.status_code == 200
    challenge = detail.json()["challenge_token"]
    assert detail.json()["label"] == "Family test"

    accepted = client.post(
        "/api/v1/auth/invitations/accept",
        json={
            "challenge_token": challenge,
            "email": "family@example.com",
            "username": "family",
            "password": "Family Password 123!",
        },
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["user"]["is_admin"] is False
    assert accepted.json()["user"]["email_verified"] is False
    assert accepted.json()["user"]["settings"]["onboarding_complete"] is False

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
        assert (
            db.scalar(select(PasswordResetToken).where(PasswordResetToken.used_at.is_not(None)))
            is not None
        )


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
        revoked = client.delete(f"/api/v1/auth/sessions/{remote['id']}", headers=csrf_headers(csrf))
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
    assert (
        client.post(
            "/api/v1/auth/logout", headers=csrf_headers(verified.json()["csrf_token"])
        ).status_code
        == 200
    )
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
        registration_mode="open",
    )
    import app.api.security as security_api
    from app.models import Base, InstallationState

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
                json={"label": "Google family"},
            ).json()
            invite_token = urlparse(invitation["invite_url"]).path.rsplit("/", 1)[-1]
            exchange = client.post(
                "/api/v1/auth/invitations/exchange", json={"token": invite_token}
            ).json()

            monkeypatch.setattr(security_api, "exchange_code", lambda _settings, _code: "id-token")

            # Start the invite flow and recover state/nonce from the authorization URL.
            started = client.get(
                "/api/v1/auth/google/start",
                params={
                    "invite_challenge": exchange["challenge_token"],
                    "return_to": "/onboarding",
                },
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
                member = db.scalar(
                    select(User).where(User.normalized_email == "google.family@example.com")
                )
                assert member is not None and member.password_hash is None
                assert (
                    db.scalar(select(AuthIdentity).where(AuthIdentity.user_id == member.id))
                    is not None
                )

            # Open registration also permits a first-time, verified Google user
            # to receive an independent Budget and begin onboarding.
            started = client.get("/api/v1/auth/google/start", follow_redirects=False)
            auth_query = parse_qs(urlparse(started.headers["location"]).query)
            state = auth_query["state"][0]
            nonce = auth_query["nonce"][0]
            monkeypatch.setattr(
                security_api,
                "validate_id_token",
                lambda _settings, _token: GoogleIdentity(
                    subject="google-open-sub",
                    email="google.open@example.com",
                    email_verified=True,
                    name="Google Open",
                    nonce=nonce,
                ),
            )
            callback = client.get(
                "/api/v1/auth/google/callback",
                params={"state": state, "code": "code"},
                follow_redirects=False,
            )
            assert callback.status_code == 302
            assert "next=/onboarding" in callback.headers["location"]
            with database.session_factory() as db:
                created = db.scalar(
                    select(User).where(User.normalized_email == "google.open@example.com")
                )
                assert created is not None and created.settings.onboarding_complete is False

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
