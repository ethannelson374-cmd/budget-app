from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from app.api.dependencies import get_db, get_settings_from_request, require_csrf, require_principal
from app.core.config import Settings
from app.schemas.api import CsvTransactionImportRequest, CsvTransactionImportView
from app.services.auth import Principal, add_audit_event
from app.services.data_portability import (
    CSV_TEMPLATE,
    bundle_json,
    export_transactions_csv,
    export_user_bundle,
    import_transactions_csv,
)

router = APIRouter(prefix="/privacy", tags=["privacy and data portability"])


@router.get("/export")
def export_data(
    principal: Principal = Depends(require_principal),
    db: Session = Depends(get_db),
) -> Response:
    payload = bundle_json(export_user_bundle(db, principal.user))
    return Response(
        content=payload,
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="budget-data-export.json"'},
    )


@router.get("/transactions.csv")
def export_csv(
    principal: Principal = Depends(require_principal),
    db: Session = Depends(get_db),
) -> Response:
    return Response(
        content=export_transactions_csv(db, principal.user),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="budget-transactions.csv"'},
    )


@router.get("/import-template.csv")
def import_template(principal: Principal = Depends(require_principal)) -> Response:
    del principal
    return Response(
        content=CSV_TEMPLATE,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="budget-transaction-import-template.csv"'},
    )


@router.post("/import-transactions", response_model=CsvTransactionImportView)
def import_transactions(
    payload: CsvTransactionImportRequest,
    request: Request,
    principal: Principal = Depends(require_csrf),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_from_request),
) -> dict[str, object]:
    result = import_transactions_csv(
        db,
        principal.user,
        account_id=payload.account_id,
        csv_text=payload.csv_text,
    )
    add_audit_event(
        db,
        settings,
        action="privacy.csv_import",
        outcome="success",
        request_id=getattr(request.state, "request_id", None),
        user_id=principal.user.id,
        detail=f"account:{payload.account_id};imported:{result['imported']};duplicates:{result['skipped_duplicates']};errors:{len(result['errors'])}",
    )
    db.commit()
    return result
