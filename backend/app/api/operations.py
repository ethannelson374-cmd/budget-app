from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.dependencies import get_db, get_settings_from_request, require_principal
from app.core.config import Settings
from app.core.errors import ApiError
from app.schemas.api import OperationsStatusView
from app.services.auth import Principal
from app.services.operations import operations_status

router = APIRouter(prefix="/operations", tags=["operations"])


@router.get("/status", response_model=OperationsStatusView)
def status(
    principal: Principal = Depends(require_principal),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_from_request),
) -> dict[str, object]:
    if not principal.user.is_admin:
        raise ApiError(403, "admin_required", "Administrator access is required")
    return operations_status(db, settings)
