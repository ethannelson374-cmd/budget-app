from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.dependencies import get_db, require_principal
from app.schemas.api import TrendsView
from app.services.auth import Principal
from app.services.trends import trends_view

router = APIRouter(prefix="/trends", tags=["trends"])
TrendRange = Literal["30d", "3m", "6m", "ytd", "1y", "all"]


@router.get("", response_model=TrendsView)
def get_trends(
    range_key: Annotated[TrendRange, Query(alias="range")] = "6m",
    principal: Principal = Depends(require_principal),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    return trends_view(db, principal.user, range_key)
