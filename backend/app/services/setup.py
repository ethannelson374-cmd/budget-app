from __future__ import annotations

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import ApiError
from app.core.security import constant_time_matches, hash_password, normalize_identity, utc_now
from app.models import Category, InstallationState, User, UserSettings
from app.schemas.api import SetupRequest
from app.services.catalog import CATEGORY_BY_KEY, DEFAULT_CATEGORIES

INSTALLATION_ROW_ID = 1


def ensure_installation_state(db: Session) -> InstallationState:
    state = db.get(InstallationState, INSTALLATION_ROW_ID)
    if state is None:
        state = InstallationState(id=INSTALLATION_ROW_ID, initialized_at=None)
        db.add(state)
        db.commit()
    return state


def installation_initialized(db: Session) -> bool:
    state = db.get(InstallationState, INSTALLATION_ROW_ID)
    return bool(state and state.initialized_at is not None)


def validate_category_keys(keys: list[str]) -> set[str]:
    selected = set(keys)
    unknown = sorted(selected.difference(CATEGORY_BY_KEY))
    if unknown:
        raise ApiError(422, "invalid_categories", "One or more selected categories are invalid")
    selected.add("other")
    return selected


def create_initial_user(
    db: Session,
    settings: Settings,
    payload: SetupRequest,
    supplied_bootstrap_token: str | None,
) -> User:
    state = db.get(InstallationState, INSTALLATION_ROW_ID)
    if state is None:
        raise ApiError(503, "setup_unavailable", "Initial setup is not available")
    if state.initialized_at is not None:
        raise ApiError(409, "already_initialized", "Initial setup has already been completed")

    configured_token = settings.bootstrap_token
    if settings.is_production and configured_token is None:
        raise ApiError(
            503,
            "setup_unavailable",
            "Initial setup is unavailable until deployment configuration is complete",
        )
    if configured_token is not None and (
        supplied_bootstrap_token is None
        or not constant_time_matches(supplied_bootstrap_token, configured_token.get_secret_value())
    ):
        raise ApiError(403, "invalid_bootstrap_token", "Initial setup is not authorized")

    try:
        claimed_at = utc_now()
        claimed = db.execute(
            update(InstallationState)
            .where(
                InstallationState.id == INSTALLATION_ROW_ID,
                InstallationState.initialized_at.is_(None),
            )
            .values(initialized_at=claimed_at)
        )
        if claimed.rowcount != 1:
            db.rollback()
            raise ApiError(409, "already_initialized", "Initial setup has already been completed")

        selected = validate_category_keys(payload.category_keys)
        user = User(
            username=payload.username,
            normalized_username=normalize_identity(payload.username),
            email=str(payload.email),
            normalized_email=normalize_identity(str(payload.email)),
            password_hash=hash_password(payload.password),
            settings=UserSettings(
                currency=payload.currency,
                timezone=payload.timezone,
                theme=payload.theme,
                annual_gross_income=payload.annual_gross_income,
                pay_frequency=payload.pay_frequency,
                onboarding_complete=True,
            ),
        )
        db.add(user)
        db.flush()
        for definition in DEFAULT_CATEGORIES:
            db.add(
                Category(
                    user_id=user.id,
                    stable_key=definition["key"],
                    name=definition["name"],
                    icon=definition["icon"],
                    enabled=definition["key"] in selected,
                )
            )
        db.flush()
        return user
    except IntegrityError as exc:
        db.rollback()
        raise ApiError(
            409, "already_initialized", "Initial setup has already been completed"
        ) from exc
