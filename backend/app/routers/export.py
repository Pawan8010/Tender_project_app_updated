import csv
import re
from datetime import date, datetime, time, timedelta
from io import BytesIO, StringIO

from fastapi import APIRouter, Depends, Response
from openpyxl import Workbook
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models import Tender

router = APIRouter(dependencies=[Depends(get_current_user)])


def _opening_date(tender) -> str:
    if tender.opening_date:
        return tender.opening_date.isoformat()
    raw_data = tender.raw_data or {}
    if raw_data.get("opening_date"):
        return raw_data["opening_date"]
    return ""


def _bracket_values(text: str | None) -> list[str]:
    return [match.strip() for match in re.findall(r"\[([^\]]+)\]", text or "") if match.strip()]


def _tender_number(tender) -> str:
    raw_data = tender.raw_data or {}
    brackets = _bracket_values(tender.description)
    return (
        tender.bid_number
        or raw_data.get("bid_number")
        or raw_data.get("tender_display_id")
        or (brackets[2] if len(brackets) >= 3 else "")
        or raw_data.get("tender_number")
        or f"TW-{tender.id:05d}"
    )


def _reference_number(tender) -> str:
    raw_data = tender.raw_data or {}
    brackets = _bracket_values(tender.description)
    return (
        tender.reference_number
        or raw_data.get("nit_id")
        or raw_data.get("procurement_id")
        or (brackets[1] if len(brackets) >= 2 else "")
        or raw_data.get("tender_number")
        or raw_data.get("bid_number")
        or tender.tender_id
    )


def _department_name(tender) -> str:
    raw_data = tender.raw_data or {}
    department = tender.department or tender.buyer or tender.organization or raw_data.get("department") or raw_data.get("buyer")
    if department:
        return department
    if re.search(r"\]\s*[^\]]+$", tender.description or ""):
        return re.sub(r"^.*\]\s*", "", tender.description or "").replace("||", " | ").strip()
    return tender.state or tender.portal or "N/A"


def _time_left(tender) -> str:
    if not tender.closing_date:
        return "N/A"
    diff = datetime.combine(tender.closing_date, time(23, 59, 59)) - datetime.now()
    if diff.total_seconds() <= 0:
        return "Closed"
    total_minutes = int(diff.total_seconds() // 60)
    days = total_minutes // 1440
    hours = (total_minutes % 1440) // 60
    minutes = total_minutes % 60
    return f"{days:02d}:{hours:02d}:{minutes:02d}"


EXPORT_COLUMNS = ["SL No.", "Tender/RFQ ID", "Tender Description", "Reference No.", "Department", "Opening Date", "Closing Date", "Time left (DD:HH:MM)", "Portal", "State", "Matched Keywords", "URL"]


def _export_row(index: int, tender) -> list:
    return [
        index,
        _tender_number(tender),
        tender.title,
        _reference_number(tender),
        _department_name(tender),
        _opening_date(tender),
        tender.closing_date.isoformat() if tender.closing_date else "",
        _time_left(tender),
        tender.portal,
        tender.state,
        ", ".join(tender.matched_keywords or []),
        tender.open_url or tender.tender_url,
    ]


def _rows(
    db: Session,
    search: str | None,
    category: str | None,
    portal: str | None,
    state: str | None,
    date_from: date | None,
    date_to: date | None,
    opening_from: date | None,
    opening_to: date | None,
    closing_from: date | None,
    closing_to: date | None,
    closing_in_days: int | None,
    matched_only: bool,
):
    query = db.query(Tender).filter(Tender.is_active.is_(True))
    if search:
        query = query.filter(
            or_(
                Tender.tender_id.ilike(f"%{search}%"),
                Tender.bid_number.ilike(f"%{search}%"),
                Tender.reference_number.ilike(f"%{search}%"),
                Tender.title.ilike(f"%{search}%"),
                Tender.description.ilike(f"%{search}%"),
                Tender.portal.ilike(f"%{search}%"),
                Tender.state.ilike(f"%{search}%"),
                Tender.district.ilike(f"%{search}%"),
                Tender.department.ilike(f"%{search}%"),
                Tender.buyer.ilike(f"%{search}%"),
                Tender.organization.ilike(f"%{search}%"),
                Tender.location.ilike(f"%{search}%"),
                Tender.ai_category.ilike(f"%{search}%"),
                Tender.search_text.ilike(f"%{search}%"),
            )
        )
    if portal:
        query = query.filter(Tender.portal == portal)
    if state:
        query = query.filter(Tender.state == state)
    tenders = query.order_by(Tender.scraped_at.desc()).all()
    if matched_only:
        tenders = [t for t in tenders if (t.matched_keywords or []) or (t.categories or [])]
    if category:
        tenders = [t for t in tenders if category in (t.categories or [])]
    if date_from:
        tenders = [t for t in tenders if t.published_date and t.published_date >= date_from]
    if date_to:
        tenders = [t for t in tenders if t.published_date and t.published_date <= date_to]
    if opening_from:
        tenders = [t for t in tenders if t.opening_date and t.opening_date >= opening_from]
    if opening_to:
        tenders = [t for t in tenders if t.opening_date and t.opening_date <= opening_to]
    if closing_from:
        tenders = [t for t in tenders if t.closing_date and t.closing_date >= closing_from]
    if closing_to:
        tenders = [t for t in tenders if t.closing_date and t.closing_date <= closing_to]
    if closing_in_days:
        deadline = date.today() + timedelta(days=closing_in_days)
        tenders = [t for t in tenders if t.closing_date and date.today() <= t.closing_date <= deadline]
    return tenders


@router.get("/csv")
def export_csv(
    search: str | None = None,
    category: str | None = None,
    portal: str | None = None,
    state: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    opening_from: date | None = None,
    opening_to: date | None = None,
    closing_from: date | None = None,
    closing_to: date | None = None,
    closing_in_days: int | None = None,
    matched_only: bool = False,
    db: Session = Depends(get_db),
):
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(EXPORT_COLUMNS)
    for index, tender in enumerate(_rows(db, search, category, portal, state, date_from, date_to, opening_from, opening_to, closing_from, closing_to, closing_in_days, matched_only), start=1):
        writer.writerow(_export_row(index, tender))
    return Response(
        output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=tenders.csv"},
    )


@router.get("/excel")
def export_excel(
    search: str | None = None,
    category: str | None = None,
    portal: str | None = None,
    state: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    opening_from: date | None = None,
    opening_to: date | None = None,
    closing_from: date | None = None,
    closing_to: date | None = None,
    closing_in_days: int | None = None,
    matched_only: bool = False,
    db: Session = Depends(get_db),
):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Tenders"
    sheet.append(EXPORT_COLUMNS)
    for index, tender in enumerate(_rows(db, search, category, portal, state, date_from, date_to, opening_from, opening_to, closing_from, closing_to, closing_in_days, matched_only), start=1):
        sheet.append(_export_row(index, tender))
    stream = BytesIO()
    workbook.save(stream)
    return Response(
        stream.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=tenders.xlsx"},
    )
