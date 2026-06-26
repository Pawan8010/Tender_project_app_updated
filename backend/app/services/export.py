from io import BytesIO
import re
from datetime import datetime, time

from openpyxl import Workbook


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
        raw_data.get("bid_number")
        or raw_data.get("tender_display_id")
        or (brackets[2] if len(brackets) >= 3 else "")
        or raw_data.get("tender_number")
        or f"TW-{tender.id:05d}"
    )


def _reference_number(tender) -> str:
    raw_data = tender.raw_data or {}
    brackets = _bracket_values(tender.description)
    return (
        raw_data.get("nit_id")
        or raw_data.get("procurement_id")
        or (brackets[1] if len(brackets) >= 2 else "")
        or raw_data.get("tender_number")
        or raw_data.get("bid_number")
        or tender.tender_id
    )


def _department_name(tender) -> str:
    raw_data = tender.raw_data or {}
    department = raw_data.get("department") or raw_data.get("buyer")
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


def export_to_excel(tenders) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Tenders"
    sheet.append(EXPORT_COLUMNS)
    for index, tender in enumerate(tenders, start=1):
        sheet.append(_export_row(index, tender))
    stream = BytesIO()
    workbook.save(stream)
    return stream.getvalue()
