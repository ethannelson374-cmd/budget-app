from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.dependencies import get_db, require_principal
from app.schemas.api import (
    ReportsBudgetView,
    ReportsGoalsDebtView,
    ReportsOverviewView,
    ReportsSpendingView,
)
from app.services.auth import Principal
from app.services.reports import reports_budget, reports_goals_debt, reports_overview, reports_spending

router = APIRouter(prefix="/reports", tags=["reports"])
ReportRange = Literal["30d", "3m", "6m", "ytd", "1y"]


@router.get("/overview", response_model=ReportsOverviewView)
def get_reports_overview(
    days: Annotated[int, Query(ge=1, le=3660)] = 90,
    principal: Principal = Depends(require_principal),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    return reports_overview(db, principal.user, days)


@router.get("/spending", response_model=ReportsSpendingView)
def get_reports_spending(
    range_key: Annotated[ReportRange, Query(alias="range")] = "6m",
    principal: Principal = Depends(require_principal),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    return reports_spending(db, principal.user, range_key)


@router.get("/budget", response_model=ReportsBudgetView)
def get_reports_budget(
    range_key: Annotated[ReportRange, Query(alias="range")] = "6m",
    principal: Principal = Depends(require_principal),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    return reports_budget(db, principal.user, range_key)


@router.get("/goals-debt", response_model=ReportsGoalsDebtView)
def get_reports_goals_debt(
    range_key: Annotated[ReportRange, Query(alias="range")] = "6m",
    principal: Principal = Depends(require_principal),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    result = reports_goals_debt(db, principal.user, range_key)
    db.commit()
    return result
