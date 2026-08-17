from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.dependencies import get_db, require_principal
from app.core.errors import ApiError
from app.schemas.api import FinancialCalendarView
from app.services.auth import Principal
from app.services.financial_calendar import financial_calendar_view

router = APIRouter(prefix="/financial-calendar", tags=["financial-calendar"])


@router.get("", response_model=FinancialCalendarView)
def get_financial_calendar(
    month: Annotated[str | None, Query(pattern=r"^\d{4}-\d{2}$")] = None,
    principal: Principal = Depends(require_principal),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    try:
        return financial_calendar_view(db, principal.user, month)
    except ValueError as exc:
        raise ApiError(422, "invalid_calendar_month", str(exc)) from exc
