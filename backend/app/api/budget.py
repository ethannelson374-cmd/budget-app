from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Request
from sqlalchemy.orm import Session

from app.api.dependencies import get_db, get_settings_from_request, require_csrf, require_principal
from app.core.config import Settings
from app.schemas.api import (
    AnnualBudgetPlanView,
    AnnualBudgetPlanWrite,
    MonthlyBudgetView,
    MonthlyBudgetWrite,
    YearBudgetView,
)
from app.services.auth import Principal, add_audit_event
from app.services.budget_planning import (
    annual_plan_view,
    copy_previous_month,
    delete_monthly_budget,
    month_budget_view,
    put_annual_plan,
    put_monthly_budget,
    year_budget_view,
)

router = APIRouter(prefix="/budget", tags=["budget"])


@router.get("/months/{month}", response_model=MonthlyBudgetView)
def get_month_budget(
    month: str,
    principal: Principal = Depends(require_principal),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    return month_budget_view(db, principal.budget_user, month)


@router.put("/months/{month}", response_model=MonthlyBudgetView)
def save_month_budget(
    month: str,
    payload: MonthlyBudgetWrite,
    request: Request,
    principal: Principal = Depends(require_csrf),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_from_request),
) -> dict[str, object]:
    put_monthly_budget(db, principal.budget_user, month, payload.model_dump())
    add_audit_event(
        db,
        settings,
        action="budget.month.update",
        outcome="success",
        request_id=getattr(request.state, "request_id", None),
        user_id=principal.user.id,
        detail=month,
    )
    db.commit()
    return month_budget_view(db, principal.budget_user, month)


@router.delete("/months/{month}", response_model=MonthlyBudgetView)
def clear_month_budget(
    month: str,
    request: Request,
    principal: Principal = Depends(require_csrf),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_from_request),
) -> dict[str, object]:
    delete_monthly_budget(db, principal.budget_user, month)
    add_audit_event(
        db,
        settings,
        action="budget.month.clear",
        outcome="success",
        request_id=getattr(request.state, "request_id", None),
        user_id=principal.user.id,
        detail=month,
    )
    db.commit()
    return month_budget_view(db, principal.budget_user, month)


@router.post("/months/{month}/copy-previous", response_model=MonthlyBudgetView)
def copy_month_budget(
    month: str,
    request: Request,
    principal: Principal = Depends(require_csrf),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_from_request),
) -> dict[str, object]:
    copy_previous_month(db, principal.budget_user, month)
    add_audit_event(
        db,
        settings,
        action="budget.month.copy_previous",
        outcome="success",
        request_id=getattr(request.state, "request_id", None),
        user_id=principal.user.id,
        detail=month,
    )
    db.commit()
    return month_budget_view(db, principal.budget_user, month)


@router.get("/years/{year}/plan", response_model=AnnualBudgetPlanView)
def get_annual_plan(
    year: Annotated[int, Path(ge=2000, le=2200)],
    principal: Principal = Depends(require_principal),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    return annual_plan_view(db, principal.budget_user, year)


@router.put("/years/{year}/plan", response_model=AnnualBudgetPlanView)
def save_annual_plan(
    year: Annotated[int, Path(ge=2000, le=2200)],
    payload: AnnualBudgetPlanWrite,
    request: Request,
    principal: Principal = Depends(require_csrf),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_from_request),
) -> dict[str, object]:
    put_annual_plan(db, principal.budget_user, year, payload.model_dump())
    add_audit_event(
        db,
        settings,
        action="budget.annual.update",
        outcome="success",
        request_id=getattr(request.state, "request_id", None),
        user_id=principal.user.id,
        detail=str(year),
    )
    db.commit()
    return annual_plan_view(db, principal.budget_user, year)


@router.get("/years/{year}", response_model=YearBudgetView)
def get_year_budget(
    year: Annotated[int, Path(ge=2000, le=2200)],
    principal: Principal = Depends(require_principal),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    return year_budget_view(db, principal.budget_user, year)
