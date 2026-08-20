from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Path, Query, Request, Response
from fastapi.responses import Response as RawResponse
from sqlalchemy.orm import Session

from app.api.dependencies import get_db, get_settings_from_request, require_csrf, require_principal
from app.core.config import Settings
from app.schemas.api import (
    ReportExportCreate,
    ReportExportListView,
    ReportExportView,
    ReportsBudgetView,
    ReportsGoalsDebtView,
    ReportsOverviewView,
    ReportsSpendingView,
    SavedReportListView,
    SavedReportView,
    SavedReportWrite,
)
from app.services.auth import Principal, add_audit_event
from app.services.report_center import (
    create_report_export,
    create_saved_report,
    delete_report_export,
    delete_saved_report,
    export_filename,
    export_view,
    get_report_export,
    list_report_exports,
    list_saved_reports,
    report_export_bytes,
    saved_report_view,
    update_saved_report,
)
from app.services.reports import reports_budget, reports_goals_debt, reports_overview, reports_spending

router = APIRouter(prefix="/reports", tags=["reports"])
ReportRange = Literal["30d", "3m", "6m", "ytd", "1y"]


def _audit(
    db: Session,
    settings: Settings,
    request: Request,
    principal: Principal,
    action: str,
    detail: str,
) -> None:
    add_audit_event(
        db,
        settings,
        action=action,
        outcome="success",
        request_id=getattr(request.state, "request_id", None),
        user_id=principal.user.id,
        detail=detail[:255],
    )


@router.get("/overview", response_model=ReportsOverviewView)
def get_reports_overview(
    days: Annotated[int, Query(ge=1, le=3660)] = 90,
    principal: Principal = Depends(require_principal),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    return reports_overview(db, principal.budget_user, days)


@router.get("/spending", response_model=ReportsSpendingView)
def get_reports_spending(
    range_key: Annotated[ReportRange, Query(alias="range")] = "6m",
    principal: Principal = Depends(require_principal),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    return reports_spending(db, principal.budget_user, range_key)


@router.get("/budget", response_model=ReportsBudgetView)
def get_reports_budget(
    range_key: Annotated[ReportRange, Query(alias="range")] = "6m",
    principal: Principal = Depends(require_principal),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    return reports_budget(db, principal.budget_user, range_key)


@router.get("/goals-debt", response_model=ReportsGoalsDebtView)
def get_reports_goals_debt(
    range_key: Annotated[ReportRange, Query(alias="range")] = "6m",
    principal: Principal = Depends(require_principal),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    result = reports_goals_debt(db, principal.budget_user, range_key)
    db.commit()
    return result


@router.get("/saved", response_model=SavedReportListView)
def get_saved_reports(
    principal: Principal = Depends(require_principal),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    return list_saved_reports(db, principal.budget_user)


@router.post("/saved", response_model=SavedReportView, status_code=201)
def post_saved_report(
    payload: SavedReportWrite,
    request: Request,
    principal: Principal = Depends(require_csrf),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_from_request),
) -> dict[str, object]:
    row = create_saved_report(
        db,
        principal.budget_user,
        name=payload.name,
        range_key=payload.range,
        sections=list(payload.sections),
    )
    _audit(db, settings, request, principal, "reports.saved.create", str(row.id))
    db.commit()
    db.refresh(row)
    return saved_report_view(row)


@router.put("/saved/{report_id}", response_model=SavedReportView)
def put_saved_report(
    report_id: Annotated[int, Path(gt=0)],
    payload: SavedReportWrite,
    request: Request,
    principal: Principal = Depends(require_csrf),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_from_request),
) -> dict[str, object]:
    row = update_saved_report(
        db,
        principal.budget_user,
        report_id,
        name=payload.name,
        range_key=payload.range,
        sections=list(payload.sections),
    )
    _audit(db, settings, request, principal, "reports.saved.update", str(row.id))
    db.commit()
    db.refresh(row)
    return saved_report_view(row)


@router.delete("/saved/{report_id}", status_code=204)
def remove_saved_report(
    report_id: Annotated[int, Path(gt=0)],
    request: Request,
    principal: Principal = Depends(require_csrf),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_from_request),
) -> Response:
    delete_saved_report(db, principal.budget_user, report_id)
    _audit(db, settings, request, principal, "reports.saved.delete", str(report_id))
    db.commit()
    return Response(status_code=204)


@router.get("/exports", response_model=ReportExportListView)
def get_report_exports(
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    principal: Principal = Depends(require_principal),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    return list_report_exports(db, principal.budget_user, limit)


@router.post("/exports", response_model=ReportExportView, status_code=201)
def post_report_export(
    payload: ReportExportCreate,
    request: Request,
    principal: Principal = Depends(require_csrf),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_from_request),
) -> dict[str, object]:
    row = create_report_export(
        db,
        principal.budget_user,
        name=payload.name,
        format_key=payload.format,
        range_key=payload.range,
        sections=list(payload.sections),
        saved_report_id=payload.saved_report_id,
    )
    _audit(db, settings, request, principal, "reports.export.create", f"{row.id}:{row.format}")
    db.commit()
    db.refresh(row)
    return export_view(row)


@router.get("/exports/{export_id}/download")
def download_report_export(
    export_id: Annotated[int, Path(gt=0)],
    request: Request,
    principal: Principal = Depends(require_principal),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_from_request),
) -> RawResponse:
    row = get_report_export(db, principal.budget_user, export_id)
    content = report_export_bytes(row)
    media_type = "text/csv; charset=utf-8" if row.format == "csv" else "application/pdf"
    _audit(db, settings, request, principal, "reports.export.download", f"{row.id}:{row.format}")
    db.commit()
    return RawResponse(
        content=content,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{export_filename(row)}"',
            "Cache-Control": "private, no-store",
            "X-Content-SHA256": row.content_sha256,
        },
    )


@router.delete("/exports/{export_id}", status_code=204)
def remove_report_export(
    export_id: Annotated[int, Path(gt=0)],
    request: Request,
    principal: Principal = Depends(require_csrf),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_from_request),
) -> Response:
    delete_report_export(db, principal.budget_user, export_id)
    _audit(db, settings, request, principal, "reports.export.delete", str(export_id))
    db.commit()
    return Response(status_code=204)
