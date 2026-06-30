import asyncio
from collections import Counter
from datetime import date, timedelta
import re

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Integer, cast, func, or_
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models import PortalRun, ScrapeLog, Tender, TenderDocument, User
from app.schemas import StatsOut, TenderList, TenderOut
from app.services.ai_intelligence import expand_query, parse_natural_search
from scrapers.registry import run_one_scraper_sync

router = APIRouter(dependencies=[Depends(get_current_user)])


def _base_query(db: Session):
    return db.query(Tender).filter(Tender.is_active.is_(True))


def _match_score(tender: Tender) -> int:
    raw_data = tender.raw_data or {}
    try:
        return int(raw_data.get("match_score") or 0)
    except (TypeError, ValueError):
        return 0


def _is_matched(tender: Tender) -> bool:
    return bool((tender.matched_keywords or []) or _match_score(tender) > 0)


SEARCH_STOP_WORDS = {
    "a",
    "an",
    "and",
    "for",
    "from",
    "in",
    "of",
    "or",
    "the",
    "this",
    "to",
    "under",
    "with",
    "week",
    "closing",
    "tenders",
}

SEARCH_GENERIC_TERMS = {
    "long",
    "range",
    "supply",
    "work",
    "works",
    "service",
    "services",
    "procurement",
    "purchase",
    "tender",
    "bid",
    "rfq",
    "rfp",
    "open",
    "closing",
    "tenders",
    "under",
    "week",
}

SEARCH_DOMAIN_TERMS = {
    "thermal",
    "imaging",
    "camera",
    "cctv",
    "ptz",
    "surveillance",
    "night",
    "vision",
    "nvd",
    "nvg",
    "drone",
    "uav",
    "anti",
    "radar",
    "radio",
    "jammer",
    "laser",
    "lrf",
    "binocular",
    "binoculars",
    "eoss",
    "optical",
    "infrared",
    "security",
    "armor",
    "helmet",
    "ballistic",
}


def _search_terms(search: str | None) -> list[str]:
    raw_terms = re.findall(r"[a-zA-Z0-9+-]{3,}", search or "")
    return [term.lower() for term in raw_terms if term.lower() not in SEARCH_STOP_WORDS]


def _expanded_search_text(search: str | None) -> str:
    if not search:
        return ""
    return " ".join(expand_query(search))


def _expanded_search_terms(search: str | None) -> list[str]:
    return _search_terms(_expanded_search_text(search))


def _important_search_terms(search: str | None) -> list[str]:
    return [term for term in _expanded_search_terms(search) if term not in SEARCH_GENERIC_TERMS]


def _ai_fragments(raw_data: dict) -> list[str]:
    ai = raw_data.get("ai") if isinstance(raw_data, dict) else {}
    if not isinstance(ai, dict):
        return []
    fragments = [
        ai.get("category"),
        ai.get("summary"),
        " ".join(ai.get("tags") or []),
        " ".join(ai.get("important_dates") or []),
    ]
    entities = ai.get("entities")
    if isinstance(entities, dict):
        for value in entities.values():
            if isinstance(value, list):
                fragments.append(" ".join(str(item) for item in value))
            elif isinstance(value, str):
                fragments.append(value)
    return [str(fragment) for fragment in fragments if fragment]


def _search_phrases(search: str | None) -> list[str]:
    if not search:
        return []
    return list(dict.fromkeys([search, *expand_query(search)]))


def _term_in_text(term: str, text: str) -> bool:
    term = term.lower().strip()
    if not term:
        return False
    if len(term) <= 3:
        return re.search(rf"\b{re.escape(term)}\b", text) is not None
    return term in text


def _search_text(tender: Tender) -> str:
    raw_data = tender.raw_data or {}
    raw_values = []
    for key in (
        "department",
        "buyer",
        "organization",
        "location",
        "district",
        "tender_number",
        "tender_display_id",
        "procurement_id",
        "plain_summary",
        "source_url",
        "stable_url",
        "reference_no",
        "reference_number",
        "bid_number",
        "nit_id",
        "pdf_text",
        "ocr_text",
        "boq_text",
        "specifications",
    ):
        value = raw_data.get(key)
        if isinstance(value, (str, int, float)):
            raw_values.append(str(value))
    parts = [
        tender.tender_id,
        tender.bid_number,
        tender.reference_number,
        tender.title,
        tender.description,
        tender.portal,
        tender.state,
        tender.district,
        tender.department,
        tender.buyer,
        tender.organization,
        tender.location,
        tender.ai_category,
        tender.search_text,
        " ".join(tender.categories or []),
        " ".join(tender.matched_keywords or []),
        *raw_values,
        " ".join(raw_data.get("semantic_matches") or []),
        *_ai_fragments(raw_data),
    ]
    return " ".join(str(part) for part in parts if part).lower()


def _source_search_text(tender: Tender) -> str:
    raw_data = tender.raw_data or {}
    raw_values = []
    for key in (
        "department",
        "buyer",
        "organization",
        "location",
        "district",
        "tender_number",
        "tender_display_id",
        "procurement_id",
        "reference_no",
        "reference_number",
        "bid_number",
        "nit_id",
    ):
        value = raw_data.get(key)
        if isinstance(value, (str, int, float)):
            raw_values.append(str(value))
    parts = [
        tender.tender_id,
        tender.bid_number,
        tender.reference_number,
        tender.title,
        tender.description,
        tender.portal,
        tender.state,
        tender.district,
        tender.department,
        tender.buyer,
        tender.organization,
        tender.location,
        tender.ai_category,
        tender.search_text,
        *raw_values,
        *_ai_fragments(raw_data),
    ]
    return " ".join(str(part) for part in parts if part).lower()


def _rank_for_search(tender: Tender, search: str | None) -> int:
    if not search:
        return 0
    text = _source_search_text(tender)
    phrase = search.strip().lower()
    terms = _expanded_search_terms(search)
    important_terms = _important_search_terms(search)
    domain_terms = [term for term in terms if term in SEARCH_DOMAIN_TERMS]
    matched_terms = [term for term in terms if _term_in_text(term, text)]
    matched_important = [term for term in important_terms if _term_in_text(term, text)]
    matched_domain = [term for term in domain_terms if _term_in_text(term, text)]

    if domain_terms and not matched_domain:
        return -1000
    if important_terms and not matched_important:
        return -500

    score = 0
    if phrase and phrase in text:
        score += 100
    score += len(matched_terms) * 8
    score += len(matched_important) * 14
    score += len(matched_domain) * 20
    score -= max(0, len(domain_terms) - len(matched_domain)) * 8
    score -= max(0, len(important_terms) - len(matched_important)) * 4
    score += min(_match_score(tender), 30)
    if tender.matched_keywords:
        score += 5
    return score


def _filter_tenders(
    tenders: list[Tender],
    category: str | None,
    date_from: date | None,
    date_to: date | None,
    opening_from: date | None,
    opening_to: date | None,
    closing_from: date | None,
    closing_to: date | None,
    matched_only: bool,
    closing_in_days: int | None,
) -> list[Tender]:
    if matched_only:
        tenders = [t for t in tenders if _is_matched(t)]
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


def _apply_sql_listing_filters(
    query,
    date_from: date | None,
    date_to: date | None,
    opening_from: date | None,
    opening_to: date | None,
    closing_from: date | None,
    closing_to: date | None,
    matched_only: bool,
    closing_in_days: int | None,
):
    if matched_only:
        query = query.filter(
            or_(
                Tender.matched_keywords != [],
                cast(func.json_extract(Tender.raw_data, "$.match_score"), Integer) > 0,
            )
        )
    if date_from:
        query = query.filter(Tender.published_date >= date_from)
    if date_to:
        query = query.filter(Tender.published_date <= date_to)
    if opening_from:
        query = query.filter(Tender.opening_date >= opening_from)
    if opening_to:
        query = query.filter(Tender.opening_date <= opening_to)
    if closing_from:
        query = query.filter(Tender.closing_date >= closing_from)
    if closing_to:
        query = query.filter(Tender.closing_date <= closing_to)
    if closing_in_days:
        deadline = date.today() + timedelta(days=closing_in_days)
        query = query.filter(Tender.closing_date >= date.today(), Tender.closing_date <= deadline)
    return query


@router.get("/stats", response_model=StatsOut)
def stats(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    tenders = _base_query(db).order_by(Tender.scraped_at.desc()).all()
    today = date.today()
    matched_tenders = sorted([t for t in tenders if _is_matched(t)], key=lambda t: (_match_score(t), t.scraped_at), reverse=True)
    by_portal = Counter(t.portal or "Unknown" for t in tenders)
    matched_by_portal = Counter(t.portal or "Unknown" for t in matched_tenders)
    by_state = Counter(t.state or "Unknown" for t in tenders)
    by_category = Counter(category for t in tenders for category in (t.categories or []))
    by_keyword = Counter(keyword for t in matched_tenders for keyword in (t.matched_keywords or []))
    last_scrape = db.query(ScrapeLog).order_by(ScrapeLog.scraped_at.desc()).first()
    queued_documents = db.query(TenderDocument).filter(TenderDocument.status.in_(["queued", "processing"])).count()
    processed_documents = db.query(TenderDocument).filter(TenderDocument.status.in_(["processed", "downloaded"])).count()
    failed_documents = db.query(TenderDocument).filter(TenderDocument.status == "failed").count()
    duplicate_runs = db.query(PortalRun).with_entities(PortalRun.duplicate_count).all()
    failed_runs = db.query(PortalRun).filter(PortalRun.status.in_(["failed", "retrying", "temporarily_blocked"])).count()
    return {
        "total": len(tenders),
        "active": len(tenders),
        "matched": len(matched_tenders),
        "unmatched": max(0, len(tenders) - len(matched_tenders)),
        "unclassified": len([t for t in tenders if (t.classification_status or "UNCLASSIFIED") == "UNCLASSIFIED"]),
        "queued_documents": queued_documents,
        "processed_documents": processed_documents,
        "failed_documents": failed_documents,
        "duplicate_runs": sum(row[0] or 0 for row in duplicate_runs),
        "failed_runs": failed_runs,
        "new_today": len([t for t in tenders if t.scraped_at and t.scraped_at.date() == today]),
        "by_portal": dict(by_portal),
        "matched_by_portal": dict(matched_by_portal),
        "by_state": dict(by_state),
        "by_category": dict(by_category),
        "by_keyword": dict(by_keyword),
        "recent": tenders[:10],
        "recent_matched": matched_tenders[:10],
        "last_scrape": last_scrape,
    }


@router.get("/", response_model=TenderList)
def get_tenders(
    search: str | None = None,
    category: str | None = None,
    state: str | None = None,
    portal: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    opening_from: date | None = None,
    opening_to: date | None = None,
    closing_from: date | None = None,
    closing_to: date | None = None,
    closing_in_days: int | None = Query(None, ge=1, le=365),
    matched_only: bool = False,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=500),
    db: Session = Depends(get_db),
):
    if search:
        intent = parse_natural_search(search)
        if not state and intent.get("state"):
            state = intent["state"]
        if not closing_to and intent.get("closing_to"):
            closing_to = intent["closing_to"]
        max_value = intent.get("max_value")
    else:
        intent = {}
        max_value = None
    semantic_search = intent.get("core_query") or search

    query = _base_query(db)
    search_phrases = _search_phrases(semantic_search)
    search_term_list = _expanded_search_terms(semantic_search)
    if search:
        search_clauses = []
        for phrase in search_phrases:
            search_clauses.extend(
                [
                    Tender.tender_id.ilike(f"%{phrase}%"),
                    Tender.bid_number.ilike(f"%{phrase}%"),
                    Tender.reference_number.ilike(f"%{phrase}%"),
                    Tender.title.ilike(f"%{phrase}%"),
                    Tender.description.ilike(f"%{phrase}%"),
                    Tender.portal.ilike(f"%{phrase}%"),
                    Tender.state.ilike(f"%{phrase}%"),
                    Tender.district.ilike(f"%{phrase}%"),
                    Tender.department.ilike(f"%{phrase}%"),
                    Tender.buyer.ilike(f"%{phrase}%"),
                    Tender.organization.ilike(f"%{phrase}%"),
                    Tender.location.ilike(f"%{phrase}%"),
                    Tender.ai_category.ilike(f"%{phrase}%"),
                    Tender.search_text.ilike(f"%{phrase}%"),
                ]
            )
        for term in search_term_list:
            search_clauses.extend(
                [
                    Tender.tender_id.ilike(f"%{term}%"),
                    Tender.bid_number.ilike(f"%{term}%"),
                    Tender.reference_number.ilike(f"%{term}%"),
                    Tender.title.ilike(f"%{term}%"),
                    Tender.description.ilike(f"%{term}%"),
                    Tender.portal.ilike(f"%{term}%"),
                    Tender.state.ilike(f"%{term}%"),
                    Tender.district.ilike(f"%{term}%"),
                    Tender.department.ilike(f"%{term}%"),
                    Tender.buyer.ilike(f"%{term}%"),
                    Tender.organization.ilike(f"%{term}%"),
                    Tender.location.ilike(f"%{term}%"),
                    Tender.ai_category.ilike(f"%{term}%"),
                    Tender.search_text.ilike(f"%{term}%"),
                ]
            )
        query = query.filter(or_(*search_clauses))
    if state:
        query = query.filter(Tender.state == state)
    if portal:
        query = query.filter(Tender.portal == portal)

    if not search and not category and not max_value:
        fast_query = _apply_sql_listing_filters(
            query,
            date_from,
            date_to,
            opening_from,
            opening_to,
            closing_from,
            closing_to,
            matched_only,
            closing_in_days,
        )
        total = fast_query.count()
        rows = (
            fast_query.order_by(Tender.scraped_at.desc())
            .offset((page - 1) * limit)
            .limit(limit)
            .all()
        )
        return {"total": total, "page": page, "limit": limit, "results": rows}

    filtered = _filter_tenders(
        query.order_by(Tender.scraped_at.desc()).all(),
        category,
        date_from,
        date_to,
        opening_from,
        opening_to,
        closing_from,
        closing_to,
        matched_only,
        closing_in_days,
    )
    if max_value:
        filtered = [tender for tender in filtered if tender.estimated_value is None or tender.estimated_value <= max_value]
    if search:
        phrases = [phrase.strip().lower() for phrase in search_phrases if phrase.strip()]
        terms = _expanded_search_terms(semantic_search)
        extra_query = _base_query(db)
        if state:
            extra_query = extra_query.filter(Tender.state == state)
        if portal:
            extra_query = extra_query.filter(Tender.portal == portal)
        existing_ids = {t.id for t in filtered}
        metadata_matches = []
        for tender in extra_query.order_by(Tender.scraped_at.desc()).limit(5000).all():
            if tender.id in existing_ids:
                continue
            text = _search_text(tender)
            phrase_match = any(_term_in_text(phrase, text) if len(phrase) <= 3 else phrase in text for phrase in phrases)
            if phrase_match or any(_term_in_text(term, text) for term in terms):
                metadata_matches.append(tender)
        if metadata_matches:
            filtered = _filter_tenders(
                [*filtered, *metadata_matches],
                category,
                date_from,
                date_to,
                opening_from,
                opening_to,
                closing_from,
                closing_to,
                matched_only,
                closing_in_days,
            )
            if max_value:
                filtered = [tender for tender in filtered if tender.estimated_value is None or tender.estimated_value <= max_value]
    if search:
        scored = [(tender, _rank_for_search(tender, semantic_search)) for tender in filtered]
        positive = [(tender, score) for tender, score in scored if score > 0]
        filtered = [tender for tender, _score in positive]

    if matched_only:
        filtered = sorted(filtered, key=lambda t: (_match_score(t), t.scraped_at), reverse=True)
    elif search:
        filtered = sorted(filtered, key=lambda t: (_rank_for_search(t, semantic_search), t.scraped_at), reverse=True)
    total = len(filtered)
    start = (page - 1) * limit
    return {"total": total, "page": page, "limit": limit, "results": filtered[start : start + limit]}


@router.get("/{tender_id}", response_model=TenderOut)
def get_tender_detail(tender_id: int, db: Session = Depends(get_db)):
    tender = _base_query(db).filter(Tender.id == tender_id).first()
    if not tender:
        raise HTTPException(status_code=404, detail="Tender not found")
    return tender


@router.post("/trigger/{portal_name}")
async def trigger_portal_scrape(portal_name: str, user: User = Depends(get_current_user)):
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    result = await asyncio.to_thread(run_one_scraper_sync, portal_name)
    if result.get("status") == "not_found":
        raise HTTPException(status_code=404, detail="Portal not found")
    return result
