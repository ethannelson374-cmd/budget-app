from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.dependencies import get_db, require_principal
from app.schemas.api import ReportsOverviewView
from app.services.auth import Principal
from app.services.reports import reports_overview

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/overview", response_model=ReportsOverviewView)
def get_reports_overview(
    days: Annotated[int, Query(ge=1, le=3660)] = 90,
    principal: Principal = Depends(require_principal),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    return reports_overview(db, principal.user, days)
