from __future__ import annotations

from datetime import date


def _date_text(value) -> str:
    if not value:
        return "no date published"
    if isinstance(value, date):
        return value.isoformat()
    return str(value)[:10]


def plain_tender_summary(tender: dict) -> str:
    title = " ".join(str(tender.get("title") or "this tender").split())
    portal = tender.get("portal") or "the source portal"
    state = tender.get("state") or "National"
    closing = _date_text(tender.get("closing_date"))
    opening = _date_text(tender.get("opening_date") or (tender.get("raw_data") or {}).get("opening_date"))
    categories = ", ".join(tender.get("categories") or []) or "general procurement"
    keywords = ", ".join((tender.get("matched_keywords") or [])[:4])
    keyword_text = f" It matched your watch list for {keywords}." if keywords else ""
    return (
        f"{portal} published a {state} tender for {title[:180]}. "
        f"It is grouped under {categories}. Opening date: {opening}. Closing date: {closing}.{keyword_text}"
    )
