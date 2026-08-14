from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from datetime import datetime
from decimal import Decimal
from typing import Literal, cast

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.core.security import utc_now
from app.models import ReportExport, SavedReport, User
from app.services.reports import (
    ReportRange,
    reports_budget,
    reports_goals_debt,
    reports_overview,
    reports_spending,
)

ReportSection = Literal["overview", "spending", "budget", "goals"]
ReportFormat = Literal["csv", "pdf"]
REPORT_SECTIONS: tuple[ReportSection, ...] = ("overview", "spending", "budget", "goals")
SECTION_LABELS: dict[ReportSection, str] = {
    "overview": "Overview",
    "spending": "Spending & Cash Flow",
    "budget": "Budget Performance",
    "goals": "Goals, Debt & Forecast",
}
RANGE_DAYS: dict[ReportRange, int] = {"30d": 30, "3m": 92, "6m": 184, "ytd": 366, "1y": 365}
RANGE_LABELS: dict[ReportRange, str] = {
    "30d": "Last 30 days",
    "3m": "Last 3 months",
    "6m": "Last 6 months",
    "ytd": "Year to date",
    "1y": "Last 12 months",
}


def normalize_sections(values: list[str]) -> list[ReportSection]:
    unique: list[ReportSection] = []
    for value in values:
        if value not in REPORT_SECTIONS:
            raise ApiError(422, "report_sections_invalid", "One or more report sections are invalid")
        section = cast(ReportSection, value)
        if section not in unique:
            unique.append(section)
    if not unique:
        raise ApiError(422, "report_sections_required", "Choose at least one report section")
    return unique


def _sections_json(sections: list[ReportSection]) -> str:
    return json.dumps(sections, separators=(",", ":"))


def _sections_from_json(value: str) -> list[ReportSection]:
    try:
        raw = json.loads(value)
    except json.JSONDecodeError:
        raw = []
    return normalize_sections([str(item) for item in raw] if isinstance(raw, list) else [])


def saved_report_view(row: SavedReport) -> dict[str, object]:
    return {
        "id": row.id,
        "name": row.name,
        "range": row.range_key,
        "sections": _sections_from_json(row.sections_json),
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def list_saved_reports(db: Session, user: User) -> dict[str, object]:
    rows = list(
        db.scalars(
            select(SavedReport)
            .where(SavedReport.user_id == user.id)
            .order_by(SavedReport.updated_at.desc(), SavedReport.id.desc())
        ).all()
    )
    return {"reports": [saved_report_view(row) for row in rows]}


def _ensure_unique_name(db: Session, user: User, name: str, *, exclude_id: int | None = None) -> None:
    query = select(SavedReport.id).where(SavedReport.user_id == user.id, SavedReport.name == name)
    if exclude_id is not None:
        query = query.where(SavedReport.id != exclude_id)
    if db.scalar(query) is not None:
        raise ApiError(409, "saved_report_name_conflict", "A saved report already uses that name")


def create_saved_report(
    db: Session,
    user: User,
    *,
    name: str,
    range_key: ReportRange,
    sections: list[str],
) -> SavedReport:
    clean_name = name.strip()
    _ensure_unique_name(db, user, clean_name)
    normalized = normalize_sections(sections)
    row = SavedReport(
        user_id=user.id,
        name=clean_name,
        range_key=range_key,
        sections_json=_sections_json(normalized),
    )
    db.add(row)
    db.flush()
    return row


def get_saved_report(db: Session, user: User, report_id: int) -> SavedReport:
    row = db.scalar(
        select(SavedReport).where(SavedReport.id == report_id, SavedReport.user_id == user.id)
    )
    if row is None:
        raise ApiError(404, "saved_report_not_found", "Saved report not found")
    return row


def update_saved_report(
    db: Session,
    user: User,
    report_id: int,
    *,
    name: str,
    range_key: ReportRange,
    sections: list[str],
) -> SavedReport:
    row = get_saved_report(db, user, report_id)
    clean_name = name.strip()
    _ensure_unique_name(db, user, clean_name, exclude_id=row.id)
    row.name = clean_name
    row.range_key = range_key
    row.sections_json = _sections_json(normalize_sections(sections))
    db.flush()
    return row


def delete_saved_report(db: Session, user: User, report_id: int) -> None:
    row = get_saved_report(db, user, report_id)
    db.delete(row)
    db.flush()


def build_report_payload(
    db: Session,
    user: User,
    *,
    range_key: ReportRange,
    sections: list[str],
) -> dict[str, object]:
    normalized = normalize_sections(sections)
    payload: dict[str, object] = {
        "generated_at": utc_now(),
        "currency": user.settings.currency,
        "range": range_key,
        "range_label": RANGE_LABELS[range_key],
        "sections": normalized,
    }
    if "overview" in normalized:
        payload["overview"] = reports_overview(db, user, RANGE_DAYS[range_key])
    if "spending" in normalized:
        payload["spending"] = reports_spending(db, user, range_key)
    if "budget" in normalized:
        payload["budget"] = reports_budget(db, user, range_key)
    if "goals" in normalized:
        payload["goals"] = reports_goals_debt(db, user, range_key)
    return payload


def _sample_rows(rows: list[dict[str, object]], limit: int) -> list[dict[str, object]]:
    if len(rows) <= limit:
        return rows
    if limit <= 1:
        return [rows[-1]]
    indexes = {round(index * (len(rows) - 1) / (limit - 1)) for index in range(limit)}
    return [rows[index] for index in sorted(indexes)]


def advisor_report_context(
    db: Session,
    user: User,
    *,
    section: ReportSection,
    range_key: ReportRange,
) -> dict[str, object]:
    payload = build_report_payload(db, user, range_key=range_key, sections=[section])
    context = dict(cast(dict[str, object], payload[section]))
    # Keep attached reports bounded for AI context while preserving Budget's
    # deterministic summaries and a representative time series.
    if section == "overview":
        history = cast(list[dict[str, object]], context.get("history") or [])
        context["history"] = _sample_rows(history, 24)
    elif section == "spending":
        categories = cast(list[dict[str, object]], context.get("categories") or [])
        context["categories"] = categories[:20]
        if not user.settings.advisor_share_merchants:
            context["top_merchants"] = []
    elif section == "budget":
        categories = cast(list[dict[str, object]], context.get("categories") or [])
        context["categories"] = categories[:20]
    elif section == "goals":
        trajectory = cast(list[dict[str, object]], context.get("trajectory") or [])
        context["trajectory"] = _sample_rows(trajectory, 24)
    return {
        "section": section,
        "section_label": SECTION_LABELS[section],
        "range": range_key,
        "range_label": RANGE_LABELS[range_key],
        "data": context,
    }


def _json_payload(payload: dict[str, object]) -> str:
    return json.dumps(payload, separators=(",", ":"), default=str)


def _as_money(value: object) -> str:
    try:
        return f"${Decimal(str(value)):,.2f}"
    except Exception:
        return str(value)


def _csv_rows(payload: dict[str, object]) -> list[list[object]]:
    rows: list[list[object]] = [
        ["Budget Financial Report"],
        ["Range", payload.get("range_label", "")],
        ["Generated", payload.get("generated_at", "")],
        [],
    ]
    sections = cast(list[str], payload.get("sections") or [])
    overview = payload.get("overview")
    if "overview" in sections and isinstance(overview, dict):
        current = cast(dict[str, object], overview.get("current") or {})
        rows += [["OVERVIEW"], ["Metric", "Value"]]
        for key, label in (
            ("net_worth", "Net worth"),
            ("cash_available", "Cash available"),
            ("safe_to_spend", "Safe to spend"),
            ("total_debt", "Total debt"),
        ):
            rows.append([label, current.get(key, "0")])
        rows.append([])

    spending = payload.get("spending")
    if "spending" in sections and isinstance(spending, dict):
        summary = cast(dict[str, object], spending.get("summary") or {})
        rows += [["SPENDING & CASH FLOW"], ["Metric", "Value"]]
        for key, label in (
            ("income", "Income"),
            ("spending", "Spending"),
            ("net_cash_flow", "Net cash flow"),
            ("savings_rate", "Savings rate %"),
            ("projected_month_spending", "Projected month spend"),
        ):
            rows.append([label, summary.get(key, "")])
        rows += [[], ["Category", "Amount", "Prior", "Change", "Change %", "Transactions"]]
        for item in cast(list[dict[str, object]], spending.get("categories") or []):
            rows.append([item.get("name"), item.get("amount"), item.get("previous_amount"), item.get("change_amount"), item.get("change_pct"), item.get("transaction_count")])
        rows.append([])

    budget = payload.get("budget")
    if "budget" in sections and isinstance(budget, dict):
        summary = cast(dict[str, object], budget.get("summary") or {})
        rows += [["BUDGET PERFORMANCE"], ["Metric", "Value"]]
        for key, label in (
            ("planned_income", "Planned income"),
            ("actual_income", "Actual income"),
            ("budgeted", "Annual budget"),
            ("spent", "Spent"),
            ("remaining", "Remaining"),
            ("projected_year_end_spend", "Projected year-end spend"),
        ):
            rows.append([label, summary.get(key, "")])
        rows += [[], ["Category", "Annual plan", "YTD plan", "Spent", "YTD variance", "Annual used %"]]
        for item in cast(list[dict[str, object]], budget.get("categories") or []):
            rows.append([item.get("name"), item.get("planned_amount"), item.get("ytd_planned_amount"), item.get("spent_amount"), item.get("ytd_variance"), item.get("percent_used")])
        rows.append([])

    goals = payload.get("goals")
    if "goals" in sections and isinstance(goals, dict):
        summary = cast(dict[str, object], goals.get("summary") or {})
        rows += [["GOALS, DEBT & FORECAST"], ["Metric", "Value"]]
        for key, label in (
            ("goal_current", "Goal balances"),
            ("goal_target", "Goal targets"),
            ("total_debt", "Total debt"),
            ("interest_saved", "Interest saved"),
            ("projected_90_day", "90-day projected cash"),
            ("forecast_accuracy_pct", "Forecast accuracy %"),
        ):
            rows.append([label, summary.get(key, "")])
        rows += [[], ["Goal", "Current", "Target", "Monthly contribution", "Projected date"]]
        for item in cast(list[dict[str, object]], goals.get("goals") or []):
            rows.append([item.get("name"), item.get("current_amount"), item.get("target_amount"), item.get("monthly_contribution"), item.get("projected_date")])
        rows += [[], ["Debt", "Balance", "APR", "Planned payment", "Payoff", "Interest saved"]]
        for item in cast(list[dict[str, object]], goals.get("debts") or []):
            rows.append([item.get("name"), item.get("balance"), item.get("apr"), item.get("planned_payment"), item.get("planned_payoff_date"), item.get("interest_saved")])
    return rows


def _csv_safe(value: object) -> object:
    if not isinstance(value, str) or not value:
        return value
    if value[0] not in ("=", "+", "-", "@", "\t", "\r"):
        return value
    try:
        Decimal(value)
        return value
    except Exception:
        return "'" + value


def render_csv(payload: dict[str, object]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerows([[_csv_safe(cell) for cell in row] for row in _csv_rows(payload)])
    return ("\ufeff" + stream.getvalue()).encode("utf-8")


def _pdf_escape(value: object) -> str:
    text = str(value).encode("ascii", "replace").decode("ascii")
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


class _PdfCanvas:
    width = 612
    height = 792

    def __init__(self) -> None:
        self.pages: list[list[str]] = [[]]
        self.y = 742.0

    @property
    def page(self) -> list[str]:
        return self.pages[-1]

    def new_page(self) -> None:
        self.pages.append([])
        self.y = 742.0
        self.text(44, 764, "Budget", size=9, bold=True, color=(0.05, 0.55, 0.52))
        self.line(44, 752, 568, 752, color=(0.82, 0.85, 0.88))

    def ensure(self, needed: float) -> None:
        if self.y - needed < 48:
            self.new_page()

    def text(self, x: float, y: float, value: object, *, size: float = 10, bold: bool = False, color: tuple[float, float, float] = (0.12, 0.15, 0.2)) -> None:
        font = "/F2" if bold else "/F1"
        r, g, b = color
        self.page.append(f"BT {r:.3f} {g:.3f} {b:.3f} rg {font} {size:.1f} Tf {x:.1f} {y:.1f} Td ({_pdf_escape(value)}) Tj ET")

    def line(self, x1: float, y1: float, x2: float, y2: float, *, color: tuple[float, float, float] = (0.75, 0.78, 0.82), width: float = 0.7) -> None:
        r, g, b = color
        self.page.append(f"q {r:.3f} {g:.3f} {b:.3f} RG {width:.2f} w {x1:.1f} {y1:.1f} m {x2:.1f} {y2:.1f} l S Q")

    def rect(self, x: float, y: float, w: float, h: float, *, fill: tuple[float, float, float] = (0.96, 0.97, 0.98), stroke: tuple[float, float, float] = (0.85, 0.87, 0.9)) -> None:
        fr, fg, fb = fill
        sr, sg, sb = stroke
        self.page.append(f"q {fr:.3f} {fg:.3f} {fb:.3f} rg {sr:.3f} {sg:.3f} {sb:.3f} RG {x:.1f} {y:.1f} {w:.1f} {h:.1f} re B Q")

    def heading(self, eyebrow: str, title: str) -> None:
        self.ensure(42)
        self.text(44, self.y, eyebrow.upper(), size=7.5, bold=True, color=(0.05, 0.55, 0.52))
        self.y -= 17
        self.text(44, self.y, title, size=15, bold=True)
        self.y -= 18

    def kpis(self, items: list[tuple[str, str]]) -> None:
        self.ensure(72)
        gap = 8
        width = (524 - gap * (len(items) - 1)) / len(items)
        y = self.y - 58
        for index, (label, value) in enumerate(items):
            x = 44 + index * (width + gap)
            self.rect(x, y, width, 54)
            self.text(x + 9, y + 36, label, size=7.5, color=(0.35, 0.4, 0.47))
            self.text(x + 9, y + 16, value, size=12, bold=True, color=(0.04, 0.45, 0.42))
        self.y = y - 18

    def table(self, headers: list[str], rows: list[list[object]], widths: list[float] | None = None, *, max_rows: int = 12) -> None:
        rows = rows[:max_rows]
        if widths is None:
            widths = [524 / len(headers)] * len(headers)
        row_h = 18
        self.ensure(row_h * (len(rows) + 2) + 8)
        x = 44.0
        self.rect(44, self.y - row_h + 3, 524, row_h, fill=(0.91, 0.94, 0.96))
        cursor = x
        for header, width in zip(headers, widths, strict=True):
            self.text(cursor + 5, self.y - 9, header, size=6.7, bold=True, color=(0.28, 0.32, 0.38))
            cursor += width
        self.y -= row_h
        for row in rows:
            cursor = x
            self.line(44, self.y + 3, 568, self.y + 3, color=(0.9, 0.91, 0.93), width=0.4)
            for value, width in zip(row, widths, strict=True):
                text = str(value)
                limit = max(6, int(width / 5.8))
                if len(text) > limit:
                    text = text[: max(1, limit - 1)] + "~"
                self.text(cursor + 5, self.y - 9, text, size=6.7)
                cursor += width
            self.y -= row_h
        self.y -= 8

    def bars(self, items: list[tuple[str, Decimal]], *, currency: bool = True) -> None:
        items = items[:8]
        if not items:
            return
        self.ensure(24 * len(items) + 8)
        maximum = max((abs(value) for _, value in items), default=Decimal("1")) or Decimal("1")
        for label, value in items:
            self.text(44, self.y, label, size=7.5)
            bar_x = 160
            bar_w = float(abs(value) / maximum) * 270
            self.rect(bar_x, self.y - 3, max(1.5, bar_w), 7, fill=(0.18, 0.72, 0.68), stroke=(0.18, 0.72, 0.68))
            shown = _as_money(value) if currency else str(value)
            self.text(442, self.y, shown, size=7.5, bold=True)
            self.y -= 22
        self.y -= 4

    def bytes(self) -> bytes:
        objects: list[bytes] = []
        objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
        objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>")
        page_object_ids: list[int] = []
        content_ids: list[int] = []
        # Reserve page/content object ids after font objects. Pages tree and catalog follow later.
        for commands in self.pages:
            content = "\n".join(commands).encode("latin-1", "replace")
            content_ids.append(len(objects) + 1)
            objects.append(b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream")
            page_object_ids.append(len(objects) + 1)
            objects.append(b"")
        pages_id = len(objects) + 1
        kids = " ".join(f"{pid} 0 R" for pid in page_object_ids)
        objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {len(page_object_ids)} >>".encode())
        catalog_id = len(objects) + 1
        objects.append(f"<< /Type /Catalog /Pages {pages_id} 0 R >>".encode())
        for index, pid in enumerate(page_object_ids):
            objects[pid - 1] = (
                f"<< /Type /Page /Parent {pages_id} 0 R /MediaBox [0 0 612 792] "
                f"/Resources << /Font << /F1 1 0 R /F2 2 0 R >> >> "
                f"/Contents {content_ids[index]} 0 R >>"
            ).encode()
        output = bytearray(b"%PDF-1.4\n%Budget\n")
        offsets = [0]
        for number, obj in enumerate(objects, start=1):
            offsets.append(len(output))
            output.extend(f"{number} 0 obj\n".encode())
            output.extend(obj)
            output.extend(b"\nendobj\n")
        xref = len(output)
        output.extend(f"xref\n0 {len(objects)+1}\n".encode())
        output.extend(b"0000000000 65535 f \n")
        for offset in offsets[1:]:
            output.extend(f"{offset:010d} 00000 n \n".encode())
        output.extend(
            f"trailer\n<< /Size {len(objects)+1} /Root {catalog_id} 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
        )
        return bytes(output)


def render_pdf(payload: dict[str, object]) -> bytes:
    pdf = _PdfCanvas()
    pdf.text(44, 748, "BUDGET", size=9, bold=True, color=(0.05, 0.55, 0.52))
    pdf.text(44, 716, "Financial Report", size=24, bold=True)
    pdf.text(44, 695, payload.get("range_label", ""), size=11, color=(0.35, 0.4, 0.47))
    pdf.text(44, 678, f"Generated {payload.get('generated_at', '')}", size=8, color=(0.45, 0.49, 0.55))
    pdf.line(44, 660, 568, 660)
    pdf.y = 632
    sections = cast(list[str], payload.get("sections") or [])

    overview = payload.get("overview")
    if "overview" in sections and isinstance(overview, dict):
        current = cast(dict[str, object], overview.get("current") or {})
        pdf.heading("Overview", "Current financial position")
        pdf.kpis([
            ("Net worth", _as_money(current.get("net_worth", 0))),
            ("Cash available", _as_money(current.get("cash_available", 0))),
            ("Safe to spend", _as_money(current.get("safe_to_spend", 0))),
            ("Total debt", _as_money(current.get("total_debt", 0))),
        ])

    spending = payload.get("spending")
    if "spending" in sections and isinstance(spending, dict):
        summary = cast(dict[str, object], spending.get("summary") or {})
        pdf.heading("Spending", "Spending & cash flow")
        pdf.kpis([
            ("Income", _as_money(summary.get("income", 0))),
            ("Spending", _as_money(summary.get("spending", 0))),
            ("Net cash flow", _as_money(summary.get("net_cash_flow", 0))),
            ("Projected month", _as_money(summary.get("projected_month_spending", 0))),
        ])
        categories = cast(list[dict[str, object]], spending.get("categories") or [])
        pdf.text(44, pdf.y, "Top spending categories", size=10, bold=True)
        pdf.y -= 18
        pdf.bars([(str(row.get("name", "Other")), Decimal(str(row.get("amount", "0")))) for row in categories])

    budget = payload.get("budget")
    if "budget" in sections and isinstance(budget, dict):
        summary = cast(dict[str, object], budget.get("summary") or {})
        pdf.heading("Budget", "Budget performance")
        pdf.kpis([
            ("Annual budget", _as_money(summary.get("budgeted", 0))),
            ("Spent", _as_money(summary.get("spent", 0))),
            ("Remaining", _as_money(summary.get("remaining", 0))),
            ("Projected year end", _as_money(summary.get("projected_year_end_spend", 0))),
        ])
        categories = cast(list[dict[str, object]], budget.get("categories") or [])
        pdf.table(
            ["Category", "YTD plan", "Spent", "YTD variance", "Annual used"],
            [[row.get("name"), _as_money(row.get("ytd_planned_amount", 0)), _as_money(row.get("spent_amount", 0)), _as_money(row.get("ytd_variance", 0)), f"{row.get('percent_used') or '-'}%"] for row in categories],
            [150, 92, 92, 100, 90],
        )

    goals = payload.get("goals")
    if "goals" in sections and isinstance(goals, dict):
        summary = cast(dict[str, object], goals.get("summary") or {})
        pdf.heading("Goals & Debt", "Goals, debt & forecast")
        pdf.kpis([
            ("Goal balances", _as_money(summary.get("goal_current", 0))),
            ("Total debt", _as_money(summary.get("total_debt", 0))),
            ("Interest saved", _as_money(summary.get("interest_saved", 0))),
            ("90-day cash", _as_money(summary.get("projected_90_day", 0))),
        ])
        goal_rows = cast(list[dict[str, object]], goals.get("goals") or [])
        if goal_rows:
            pdf.text(44, pdf.y, "Active goals", size=10, bold=True)
            pdf.y -= 15
            pdf.table(
                ["Goal", "Current", "Target", "Monthly", "Projected"],
                [[row.get("name"), _as_money(row.get("current_amount", 0)), _as_money(row.get("target_amount", 0)), _as_money(row.get("monthly_contribution", 0)), row.get("projected_date") or "-"] for row in goal_rows],
                [150, 92, 92, 85, 105],
            )
        debt_rows = cast(list[dict[str, object]], goals.get("debts") or [])
        if debt_rows:
            pdf.text(44, pdf.y, "Debt payoff", size=10, bold=True)
            pdf.y -= 15
            pdf.table(
                ["Debt", "Balance", "APR", "Payment", "Payoff", "Saved"],
                [[row.get("name"), _as_money(row.get("balance", 0)), f"{row.get('apr')}%", _as_money(row.get("planned_payment", 0)), row.get("planned_payoff_date") or "-", _as_money(row.get("interest_saved", 0))] for row in debt_rows],
                [130, 82, 62, 82, 92, 76],
            )

    pdf.ensure(34)
    pdf.line(44, pdf.y, 568, pdf.y)
    pdf.y -= 18
    pdf.text(44, pdf.y, "Generated by Budget from deterministic financial calculations. AI is not used to calculate report values.", size=7.2, color=(0.45, 0.49, 0.55))
    return pdf.bytes()


def render_export(payload: dict[str, object], format_key: ReportFormat) -> bytes:
    return render_csv(payload) if format_key == "csv" else render_pdf(payload)


def export_view(row: ReportExport) -> dict[str, object]:
    return {
        "id": row.id,
        "saved_report_id": row.saved_report_id,
        "name": row.name,
        "format": row.format,
        "range": row.range_key,
        "sections": _sections_from_json(row.sections_json),
        "content_sha256": row.content_sha256,
        "file_size": row.file_size,
        "created_at": row.created_at,
    }


def create_report_export(
    db: Session,
    user: User,
    *,
    name: str,
    format_key: ReportFormat,
    range_key: ReportRange,
    sections: list[str],
    saved_report_id: int | None = None,
) -> ReportExport:
    normalized = normalize_sections(sections)
    if saved_report_id is not None:
        get_saved_report(db, user, saved_report_id)
    payload = build_report_payload(db, user, range_key=range_key, sections=normalized)
    payload_json = _json_payload(payload)
    content = render_export(json.loads(payload_json), format_key)
    row = ReportExport(
        user_id=user.id,
        saved_report_id=saved_report_id,
        name=name.strip(),
        format=format_key,
        range_key=range_key,
        sections_json=_sections_json(normalized),
        payload_json=payload_json,
        content_blob=content,
        content_sha256=hashlib.sha256(content).hexdigest(),
        file_size=len(content),
        created_at=utc_now(),
    )
    db.add(row)
    db.flush()
    return row


def list_report_exports(db: Session, user: User, limit: int = 20) -> dict[str, object]:
    rows = list(
        db.scalars(
            select(ReportExport)
            .where(ReportExport.user_id == user.id)
            .order_by(ReportExport.created_at.desc(), ReportExport.id.desc())
            .limit(limit)
        ).all()
    )
    return {"exports": [export_view(row) for row in rows]}


def get_report_export(db: Session, user: User, export_id: int) -> ReportExport:
    row = db.scalar(
        select(ReportExport).where(ReportExport.id == export_id, ReportExport.user_id == user.id)
    )
    if row is None:
        raise ApiError(404, "report_export_not_found", "Report export not found")
    return row


def report_export_bytes(row: ReportExport) -> bytes:
    content = bytes(row.content_blob)
    if len(content) != row.file_size or hashlib.sha256(content).hexdigest() != row.content_sha256:
        raise ApiError(500, "report_export_corrupt", "Stored report export failed its integrity check")
    return content


def export_filename(row: ReportExport) -> str:
    base = re.sub(r"[^A-Za-z0-9._-]+", "-", row.name.strip()).strip("-._") or "budget-report"
    return f"{base}.{row.format}"


def delete_report_export(db: Session, user: User, export_id: int) -> None:
    result = db.execute(
        delete(ReportExport).where(ReportExport.id == export_id, ReportExport.user_id == user.id)
    )
    if result.rowcount == 0:
        raise ApiError(404, "report_export_not_found", "Report export not found")
