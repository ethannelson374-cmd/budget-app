from __future__ import annotations

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, selectinload

from app.core.errors import ApiError
from app.models import BudgetMembership, User, UserInvitation
from app.models.base import utc_now


def ensure_budget_membership(db: Session, user: User) -> BudgetMembership:
    row = db.get(BudgetMembership, user.id)
    if row is not None:
        return row
    # Compatibility guard for databases created outside migrations/tests.
    row = BudgetMembership(
        user_id=user.id,
        budget_owner_user_id=user.id,
        role="owner",
        joined_at=utc_now(),
    )
    db.add(row)
    db.flush()
    return row


def budget_owner_id(db: Session, user: User) -> int:
    return ensure_budget_membership(db, user).budget_owner_user_id


def budget_user(db: Session, user: User) -> User:
    owner_id = budget_owner_id(db, user)
    owner = db.scalar(select(User).options(selectinload(User.settings)).where(User.id == owner_id))
    if owner is None:
        raise ApiError(409, "budget_membership_invalid", "The shared Budget membership is invalid")
    return owner


def create_membership(
    db: Session,
    user: User,
    *,
    budget_owner_user_id: int | None = None,
) -> BudgetMembership:
    owner_id = budget_owner_user_id or user.id
    owner = db.get(User, owner_id)
    if owner is None:
        raise ApiError(409, "budget_owner_missing", "The shared Budget owner no longer exists")
    row = BudgetMembership(
        user_id=user.id,
        budget_owner_user_id=owner_id,
        role="owner" if owner_id == user.id else "member",
        joined_at=utc_now(),
    )
    db.add(row)
    db.flush()
    return row


def family_status(db: Session, user: User) -> dict[str, object]:
    membership = ensure_budget_membership(db, user)
    owner = db.get(User, membership.budget_owner_user_id)
    members = list(
        db.scalars(
            select(User)
            .join(BudgetMembership, BudgetMembership.user_id == User.id)
            .where(BudgetMembership.budget_owner_user_id == membership.budget_owner_user_id)
            .order_by(User.created_at, User.id)
        ).all()
    )
    member_rows = {
        row.user_id: row
        for row in db.scalars(
            select(BudgetMembership).where(
                BudgetMembership.budget_owner_user_id == membership.budget_owner_user_id
            )
        ).all()
    }
    return {
        "budget_owner_user_id": membership.budget_owner_user_id,
        "budget_owner_username": owner.username if owner is not None else "Budget owner",
        "role": membership.role,
        "shared": len(members) > 1,
        "members": [
            {
                "id": member.id,
                "username": member.username,
                "email": member.email,
                "role": member_rows[member.id].role,
                "is_current": member.id == user.id,
            }
            for member in members
        ],
    }


def require_no_budget_dependents(db: Session, user: User) -> None:
    membership = ensure_budget_membership(db, user)
    if membership.role != "owner":
        return
    count = int(
        db.scalar(
            select(func.count(BudgetMembership.user_id)).where(
                BudgetMembership.budget_owner_user_id == user.id,
                BudgetMembership.user_id != user.id,
            )
        )
        or 0
    )
    if count:
        raise ApiError(
            409,
            "shared_budget_has_members",
            "Remove shared Budget members before deleting the Budget owner account",
        )


def _revoke_shared_invites_for_departing_user(db: Session, user_id: int, owner_id: int) -> None:
    now = utc_now()
    db.execute(
        update(UserInvitation)
        .where(
            UserInvitation.invited_by_user_id == user_id,
            UserInvitation.invite_type == "shared",
            UserInvitation.budget_owner_user_id == owner_id,
            UserInvitation.accepted_at.is_(None),
            UserInvitation.revoked_at.is_(None),
            UserInvitation.expires_at > now,
        )
        .values(revoked_at=now, challenge_digest=None, challenge_expires_at=None)
    )


def detach_family_member(db: Session, actor: User, member_user_id: int) -> BudgetMembership:
    actor_membership = ensure_budget_membership(db, actor)
    if actor_membership.role != "owner":
        raise ApiError(403, "budget_owner_required", "Only the Budget owner can remove family members")
    if member_user_id == actor.id:
        raise ApiError(409, "budget_owner_cannot_remove_self", "The Budget owner cannot remove themselves")
    member = db.get(BudgetMembership, member_user_id)
    if member is None or member.budget_owner_user_id != actor.id or member.role != "member":
        raise ApiError(404, "budget_member_not_found", "The shared Budget member was not found")
    _revoke_shared_invites_for_departing_user(db, member_user_id, actor.id)
    member.budget_owner_user_id = member_user_id
    member.role = "owner"
    member.joined_at = utc_now()
    db.flush()
    return member


def leave_shared_budget(db: Session, user: User) -> BudgetMembership:
    membership = ensure_budget_membership(db, user)
    if membership.role != "member":
        raise ApiError(409, "not_shared_budget_member", "This account is not a member of another Budget")
    old_owner_id = membership.budget_owner_user_id
    _revoke_shared_invites_for_departing_user(db, user.id, old_owner_id)
    membership.budget_owner_user_id = user.id
    membership.role = "owner"
    membership.joined_at = utc_now()
    db.flush()
    return membership
