import re
import hashlib
import time
from collections import Counter
from difflib import get_close_matches
from datetime import date
from urllib.parse import quote_plus, urlparse

from fastapi import APIRouter, Depends, HTTPException, Query
import httpx
from pydantic import BaseModel, Field
from sqlalchemy import or_

from app.auth import get_current_user
from app.config import settings
from app.database import SessionLocal
from app.models import Tender, TenderSearchIndex
from app.services.ai_intelligence import cosine_similarity, expand_query, parse_natural_search, text_embedding
from app.services.ml_engine import find_similar_titles, fuzzy_search, semantic_search
from app.services.google_tender_discovery import configured_portal_queries

router = APIRouter(dependencies=[Depends(get_current_user)])

_GOOGLE_CACHE_TTL_SECONDS = 300
_GOOGLE_CACHE: dict[tuple[str, int], tuple[float, dict]] = {}
_SUGGESTION_CACHE_TTL_SECONDS = 120
_SUGGESTION_CACHE: dict[str, tuple[float, dict]] = {}
_SEARCH_CACHE_TTL_SECONDS = 90
_SEARCH_CACHE: dict[tuple[str, int], tuple[float, dict]] = {}

NON_TENDER_TITLES = {
    "tenders status",
    "active tenders",
    "cancelled/retendered",
    "tenders in archive",
    "tenders by organisation",
    "tenders by classification",
    "tenders by location",
    "view tender information",
    "mis reports",
}


class WebResultImport(BaseModel):
    query: str = Field(..., min_length=2, max_length=255)
    title: str = Field(..., min_length=3, max_length=500)
    link: str = Field(..., min_length=8, max_length=2000)
    snippet: str = Field("", max_length=5000)
    display_link: str = Field("", max_length=255)


def _normalize_web_result(item: dict, query: str) -> dict:
    link = item.get("link") or ""
    return {
        "title": item.get("title") or item.get("htmlTitle") or "Web tender result",
        "link": link,
        "snippet": item.get("snippet") or item.get("htmlSnippet") or "",
        "display_link": item.get("displayLink") or item.get("display_link") or "",
        "source": "google_programmable_search",
        "result_type": "web_tender_discovery",
        "search_query": query,
        "can_import": bool(link),
    }


def _copy_google_response(payload: dict) -> dict:
    copied = dict(payload)
    copied["results"] = [dict(item) for item in payload.get("results", [])]
    return copied


def _google_tender_queries(q: str) -> list[str]:
    clean = " ".join((q or "").split())
    if not clean:
        return []

    base_queries = [
        f"{clean} tender procurement government India",
        f'"{clean}" tender',
        f"{clean} bid tender",
    ]
    priority_domains = [
        "gem.gov.in",
        "eprocure.gov.in",
        "etenders.gov.in",
        "mahatenders.gov.in",
    ]
    try:
        configured_domains = [
            item["domain"]
            for item in configured_portal_queries(limit_portals=12)
            if item.get("domain")
        ]
    except Exception:
        configured_domains = []

    domains = list(dict.fromkeys([*priority_domains, *configured_domains]))[:12]
    site_queries = [f"site:{domain} {clean} tender" for domain in domains]
    return list(dict.fromkeys([*base_queries, *site_queries]))


def _dedupe_google_results(items: list[dict], q: str, limit: int) -> list[dict]:
    seen: set[str] = set()
    normalized: list[dict] = []
    for item in items:
        link = (item.get("link") or "").strip()
        if not link or link in seen:
            continue
        seen.add(link)
        normalized.append(_normalize_web_result(item, q))
        if len(normalized) >= limit:
            break
    return normalized


def _safe_google_error(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        detail = ""
        try:
            payload = exc.response.json()
            detail = payload.get("error", {}).get("message", "")
        except Exception:
            detail = exc.response.text[:140]
        return f"Google search request failed with HTTP {status}: {detail[:140]}"
    if isinstance(exc, httpx.TimeoutException):
        return "Google search request timed out."
    return f"Google search request failed: {exc.__class__.__name__}"


def _web_result_to_tender_data(payload: dict) -> dict:
    link = payload.get("link") or ""
    title = (payload.get("title") or "Web tender result").strip()
    snippet = (payload.get("snippet") or title).strip()
    display_link = payload.get("display_link") or payload.get("displayLink") or ""
    query = payload.get("query") or payload.get("search_query") or ""
    source_hash = hashlib.sha256(link.encode("utf-8")).hexdigest()[:18].upper()
    parsed_url = urlparse(link)
    source_name = display_link or parsed_url.netloc or "Web Discovery"
    return {
        "tender_id": f"WEB-{source_hash}",
        "reference_number": f"WEB-{source_hash}",
        "title": title[:500],
        "description": snippet,
        "portal": "Live Google Discovery",
        "state": "External",
        "department": source_name[:255],
        "organization": source_name[:255],
        "location": "Web",
        "tender_url": link,
        "published_date": date.today(),
        "closing_date": None,
        "estimated_value": None,
        "currency": "INR",
        "tender_status": "ACTIVE",
        "classification_status": "PENDING_CLASSIFICATION",
        "categories": ["Google Discovery", "Web Discovery"],
        "matched_keywords": [],
        "raw_data": {
            "source": "google_web_discovery",
            "source_url": link,
            "stable_url": link,
            "scrape_method": "google_programmable_search",
            "search_query": query,
            "display_link": display_link,
            "plain_summary": snippet,
            "requires_portal_scrape": True,
        },
    }


def _save_web_result(db, payload: dict) -> tuple[str, int, dict]:
    from scrapers.registry import _upsert_tender

    return _upsert_tender(db, _web_result_to_tender_data(payload), return_changes=True)


def _term_in_text(term: str, text: str) -> bool:
    term = term.lower().strip()
    if not term:
        return False
    if len(term) <= 3:
        return re.search(rf"\b{re.escape(term)}\b", text) is not None
    return term in text


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-zA-Z0-9+#.-]{2,}", (text or "").lower())


def _acronym(text: str) -> str:
    words = re.findall(r"[A-Za-z][A-Za-z0-9]+", text or "")
    return "".join(word[0] for word in words[:8]).lower()


def _highlight_terms(query: str, expanded_terms: list[str]) -> list[str]:
    terms = []
    for term in [query, *expanded_terms, *_tokens(query)]:
        cleaned = " ".join(str(term or "").split())
        if len(cleaned) >= 2 and cleaned.lower() not in {"tender", "tenders", "bid", "procurement"}:
            terms.append(cleaned)
    return list(dict.fromkeys(terms))[:16]


def _make_snippet(text: str, terms: list[str], size: int = 240) -> str:
    cleaned = " ".join((text or "").split())
    if not cleaned:
        return ""
    lowered = cleaned.lower()
    positions = [lowered.find(term.lower()) for term in terms if term and lowered.find(term.lower()) >= 0]
    if not positions:
        return cleaned[:size]
    start = max(0, min(positions) - 70)
    end = min(len(cleaned), start + size)
    prefix = "..." if start else ""
    suffix = "..." if end < len(cleaned) else ""
    return f"{prefix}{cleaned[start:end]}{suffix}"


def _row_search_blob(row: Tender) -> str:
    raw = row.raw_data or {}
    ai = raw.get("ai") if isinstance(raw.get("ai"), dict) else {}
    return " ".join(
        str(part)
        for part in [
            row.title,
            row.description,
            row.search_text,
            row.portal,
            row.state,
            row.department,
            row.organization,
            row.location,
            row.ai_category,
            " ".join(row.categories or []),
            " ".join(row.matched_keywords or []),
            ai.get("summary"),
            " ".join(ai.get("tags") or []),
            raw.get("detail_text"),
            raw.get("document_text"),
        ]
        if part
    )


def _recency_score(row: Tender) -> float:
    if not row.scraped_at:
        return 0.0
    age_days = max(0, (date.today() - row.scraped_at.date()).days)
    return max(0.0, 1.0 - min(age_days, 45) / 45)


def _closing_score(row: Tender) -> float:
    if not row.closing_date:
        return 0.15
    days_left = (row.closing_date - date.today()).days
    if days_left < 0:
        return 0.0
    if days_left <= 7:
        return 1.0
    if days_left <= 30:
        return 0.7
    return 0.35


def _value_score(row: Tender) -> float:
    if not row.estimated_value:
        return 0.15
    return min(1.0, float(row.estimated_value) / 50_000_000)


def _lexical_score(query: str, expanded_terms: list[str], text: str) -> tuple[float, list[str]]:
    lowered = f" {text.lower()} "
    query_lower = query.lower().strip()
    terms = _highlight_terms(query, expanded_terms)
    hits = [term for term in terms if _term_in_text(term, lowered)]
    query_tokens = _tokens(query)
    text_tokens = set(_tokens(text))
    token_hits = [term for term in query_tokens if term in text_tokens]
    fuzzy_hits = []
    if query_tokens:
        searchable = list(text_tokens)[:3000]
        for term in query_tokens:
            if term not in text_tokens and get_close_matches(term, searchable, n=1, cutoff=0.86):
                fuzzy_hits.append(term)
    acronym_hits = []
    for term in query_tokens:
        if 2 <= len(term) <= 8 and term == _acronym(text):
            acronym_hits.append(term)
    phrase = 0.25 if query_lower and query_lower in lowered else 0.0
    score = min(
        1.0,
        phrase
        + min(len(hits), 8) * 0.07
        + min(len(token_hits), 8) * 0.045
        + min(len(fuzzy_hits), 4) * 0.035
        + min(len(acronym_hits), 2) * 0.05,
    )
    return score, list(dict.fromkeys([*hits, *token_hits, *fuzzy_hits, *acronym_hits]))


@router.get("/search")
def smart_search(q: str = Query(..., min_length=2), mode: str = "both", limit: int = Query(10, ge=1, le=50)):
    if mode == "fuzzy":
        results = fuzzy_search(q, limit)
    elif mode == "semantic":
        results = semantic_search(q, limit)
    else:
        seen = set()
        results = []
        for item in [*semantic_search(q, limit), *fuzzy_search(q, limit)]:
            if item["term"] not in seen:
                seen.add(item["term"])
                results.append(item)
        results = sorted(results, key=lambda row: row["score"], reverse=True)[:limit]
    return {"query": q, "mode": mode, "count": len(results), "results": results}


@router.get("/suggest")
def search_suggestions(q: str = Query(..., min_length=1), limit: int = Query(8, ge=1, le=20)):
    key = f"{q.strip().lower()}:{limit}"
    cached = _SUGGESTION_CACHE.get(key)
    if cached and time.time() - cached[0] <= _SUGGESTION_CACHE_TTL_SECONDS:
        return {**cached[1], "cached": True}

    needle = q.strip().lower()
    db = SessionLocal()
    try:
        rows = (
            db.query(Tender)
            .filter(Tender.is_active.is_(True))
            .order_by(Tender.scraped_at.desc())
            .limit(2000)
            .all()
        )
        counter = Counter()
        rich = []
        for row in rows:
            raw = row.raw_data or {}
            ai = raw.get("ai") if isinstance(raw.get("ai"), dict) else {}
            values = [
                row.title,
                row.portal,
                row.state,
                row.department,
                row.organization,
                row.ai_category,
                *(row.categories or []),
                *(row.matched_keywords or []),
                *(ai.get("tags") or []),
            ]
            for value in values:
                value = " ".join(str(value or "").split())
                if len(value) < max(2, len(needle)):
                    continue
                lowered = value.lower()
                if needle in lowered:
                    weight = 6 if lowered.startswith(needle) else 3
                    counter[value] += weight
            title_tokens = [token for token in _tokens(row.title or "") if needle in token and len(token) >= 3]
            for token in title_tokens[:8]:
                counter[token] += 2

        for value, count in counter.most_common(limit):
            rich.append({"text": value, "score": count, "type": "suggestion"})

        if len(rich) < limit:
            expanded = expand_query(q)
            for term in expanded:
                if term.lower() != needle and all(item["text"].lower() != term.lower() for item in rich):
                    rich.append({"text": term, "score": 1, "type": "ai_expansion"})
                if len(rich) >= limit:
                    break
        if not rich:
            rich = [
                {"text": q.strip(), "score": 1, "type": "search"},
                {"text": f"{q.strip()} tender", "score": 1, "type": "search"},
                {"text": f"{q.strip()} procurement", "score": 1, "type": "search"},
            ][:limit]

        payload = {"query": q, "count": len(rich), "suggestions": rich, "cached": False}
        _SUGGESTION_CACHE[key] = (time.time(), payload)
        return payload
    finally:
        db.close()


@router.get("/google")
def google_search(q: str = Query(..., min_length=2), limit: int = Query(6, ge=1, le=10)):
    cfg = settings()
    limit = min(max(int(limit), 1), 10)
    queries = _google_tender_queries(q)
    query = queries[0] if queries else f"{q} tender procurement government India"
    search_url = f"https://www.google.com/search?q={quote_plus(query)}"
    api_key = cfg.get("google_search_api_key")
    cx = cfg.get("google_search_cx")

    if not api_key or not cx:
        return {
            "query": q,
            "provider": "google_search_url",
            "configured": False,
            "integrated": False,
            "search_url": search_url,
            "count": 0,
            "results": [],
            "message": "Google Programmable Search is not configured. Open the Google link or set GOOGLE_SEARCH_API_KEY and GOOGLE_SEARCH_CX.",
        }

    cache_key = (q.strip().lower(), limit)
    cached = _GOOGLE_CACHE.get(cache_key)
    if cached and time.time() - cached[0] <= _GOOGLE_CACHE_TTL_SECONDS:
        response = _copy_google_response(cached[1])
        response["cached"] = True
        return response

    raw_items: list[dict] = []
    attempted_queries: list[str] = []
    try:
        with httpx.Client(timeout=12, follow_redirects=True) as client:
            for candidate_query in queries[:5]:
                attempted_queries.append(candidate_query)
                response = client.get(
                    "https://www.googleapis.com/customsearch/v1",
                    params={"key": api_key, "cx": cx, "q": candidate_query, "num": min(limit, 10), "safe": "off"},
                )
                response.raise_for_status()
                raw_items.extend(response.json().get("items", []))
                if len(_dedupe_google_results(raw_items, q, limit)) >= limit:
                    break
    except Exception as exc:
        return {
            "query": q,
            "provider": "google_programmable_search",
            "configured": True,
            "integrated": False,
            "search_url": search_url,
            "count": 0,
            "results": [],
            "message": _safe_google_error(exc),
        }

    results = _dedupe_google_results(raw_items, q, limit)
    payload = {
        "query": q,
        "provider": "google_programmable_search",
        "configured": True,
        "integrated": bool(results),
        "cached": False,
        "search_url": search_url,
        "searched_queries": attempted_queries,
        "count": len(results),
        "results": results,
        "message": (
            f"Found {len(results)} related Google tender result(s) across public web and configured portal domains."
            if results
            else "Google returned no related tender result for this query."
        ),
    }
    _GOOGLE_CACHE[cache_key] = (time.time(), _copy_google_response(payload))
    return payload


@router.post("/web/import")
def import_web_result(payload: WebResultImport):
    """Save a live web discovery result into the existing tender database."""
    db = SessionLocal()
    try:
        status, tender_id, changes = _save_web_result(db, payload.model_dump())
        db.commit()
        return {
            "status": status,
            "id": tender_id,
            "changes": changes,
            "message": "Web discovery saved into the tender system for AI classification and future searches.",
        }
    finally:
        db.close()


@router.post("/google/import")
def google_search_and_import(q: str = Query(..., min_length=2), limit: int = Query(6, ge=1, le=10)):
    """Run Google Programmable Search, store web tender results, and return saved rows."""
    google = google_search(q=q, limit=limit)
    results = google.get("results") or []
    if not results:
        return {
            **google,
            "stored": 0,
            "message": google.get("message") or "No Google results were returned to store.",
        }

    stored_results = []
    db = SessionLocal()
    try:
        for item in results:
            payload = {
                **item,
                "query": q,
                "search_query": q,
            }
            status, tender_id, changes = _save_web_result(db, payload)
            stored_results.append(
                {
                    **item,
                    "stored_id": tender_id,
                    "store_status": status,
                    "changed_fields": changes,
                    "tracked": True,
                }
            )
        db.commit()
    finally:
        db.close()

    return {
        **google,
        "integrated": True,
        "stored": len(stored_results),
        "results": stored_results,
        "message": f"Stored {len(stored_results)} Google web results in the tender system.",
    }


@router.get("/unified")
def unified_search(
    q: str = Query(..., min_length=2),
    mode: str = "both",
    tender_limit: int = Query(8, ge=1, le=50),
    web_limit: int = Query(6, ge=1, le=10),
    store_web: bool = Query(False),
    include_google: bool = Query(False),
):
    """Google-like response: local tender index first, optional Google discovery as related/fallback."""
    from scrapers.registry import scraper_runtime_status

    tenders = semantic_tender_search(q=q, limit=tender_limit)
    local_count = int(tenders.get("count", 0) or 0)
    google = {
        "query": q,
        "provider": "local_index_primary",
        "configured": bool(settings().get("google_search_api_key") and settings().get("google_search_cx")),
        "integrated": False,
        "search_url": f"https://www.google.com/search?q={quote_plus(f'{q} tender procurement government India')}",
        "count": 0,
        "results": [],
        "message": (
            "Local tender index returned results. Google related results are available on request."
            if local_count > 0
            else "Local tender index found no matches. Use Google portal discovery to import fresh public URLs."
        ),
    }
    if store_web:
        google = google_search_and_import(q=q, limit=web_limit)
        if google.get("stored", 0) > 0:
            tenders = semantic_tender_search(q=q, limit=tender_limit)
    elif include_google or local_count == 0:
        google = google_search(q=q, limit=web_limit)
    terms = smart_search(q=q, mode=mode, limit=12)
    runtime = scraper_runtime_status()
    return {
        "query": q,
        "order": ["google", "ai_tenders", "related_terms"],
        "google": google,
        "ai_tenders": tenders,
        "related_terms": terms,
        "scraper": {
            "running": runtime.get("running"),
            "portal_count": runtime.get("portal_count"),
            "last_status": runtime.get("last_status"),
            "concurrency": runtime.get("concurrency"),
        },
    }


@router.get("/similar/{tender_id}")
def similar_tenders(tender_id: int, limit: int = Query(5, ge=1, le=20)):
    db = SessionLocal()
    try:
        target = db.get(Tender, tender_id)
        if not target:
            raise HTTPException(status_code=404, detail="Tender not found")
        candidates = db.query(Tender).filter(Tender.id != tender_id, Tender.is_active.is_(True)).order_by(Tender.scraped_at.desc()).limit(500).all()
        matches = find_similar_titles(target.title, [row.title for row in candidates], limit)
        return {
            "target_id": tender_id,
            "target_title": target.title,
            "similar": [{**item, "tender_id": candidates[item["index"]].id, "portal": candidates[item["index"]].portal} for item in matches],
        }
    finally:
        db.close()


@router.get("/tenders")
def semantic_tender_search(
    q: str = Query(..., min_length=2),
    limit: int = Query(20, ge=1, le=100),
    portal: str | None = None,
    state: str | None = None,
    department: str | None = None,
    category: str | None = None,
    organization: str | None = None,
    tender_status: str | None = None,
    min_value: float | None = None,
    max_value: float | None = None,
    published_from: date | None = None,
    published_to: date | None = None,
    closing_from: date | None = None,
    closing_to: date | None = None,
):
    cache_key = (
        q.strip().lower(),
        limit,
        portal or "",
        state or "",
        department or "",
        category or "",
        organization or "",
        tender_status or "",
        min_value or 0,
        max_value or 0,
        str(published_from or ""),
        str(published_to or ""),
        str(closing_from or ""),
        str(closing_to or ""),
    )
    cached = _SEARCH_CACHE.get(cache_key)
    if cached and time.time() - cached[0] <= _SEARCH_CACHE_TTL_SECONDS:
        return {**cached[1], "cached": True}

    intent = parse_natural_search(q)
    expanded_terms = intent.get("expanded_terms") or expand_query(q)
    query_vector = text_embedding(" ".join(expanded_terms))
    highlight_terms = _highlight_terms(q, expanded_terms)
    db = SessionLocal()
    try:
        search_terms = [
            term
            for term in _highlight_terms(q, expanded_terms)
            if len(term) > 2 and term.lower() not in {"tender", "tenders", "procurement"}
        ][:10]
        def active_query():
            return db.query(Tender).filter(Tender.is_active.is_(True))

        def add_rows(existing: list[Tender], new_rows: list[Tender], cap: int = 700) -> list[Tender]:
            seen = {row.id for row in existing}
            for item in new_rows:
                if item.id not in seen:
                    existing.append(item)
                    seen.add(item.id)
                if len(existing) >= cap:
                    break
            return existing

        rows: list[Tender] = []
        exact_phrase = q.strip()
        if exact_phrase:
            exact_pattern = f"%{exact_phrase}%"
            exact_rows = (
                active_query()
                .filter(
                    or_(
                        Tender.title.ilike(exact_pattern),
                        Tender.bid_number.ilike(exact_pattern),
                        Tender.reference_number.ilike(exact_pattern),
                    )
                )
                .order_by(Tender.scraped_at.desc())
                .limit(max(80, limit * 8))
                .all()
            )
            rows = add_rows(rows, exact_rows)

        if search_terms:
            clauses = []
            for term in search_terms:
                pattern = f"%{term}%"
                clauses.extend(
                    [
                        Tender.title.ilike(pattern),
                        Tender.description.ilike(pattern),
                        Tender.portal.ilike(pattern),
                        Tender.state.ilike(pattern),
                        Tender.department.ilike(pattern),
                        Tender.organization.ilike(pattern),
                        Tender.bid_number.ilike(pattern),
                        Tender.reference_number.ilike(pattern),
                        Tender.ai_category.ilike(pattern),
                    ]
                )
            term_rows = active_query().filter(or_(*clauses)).order_by(Tender.scraped_at.desc()).limit(500).all()
            rows = add_rows(rows, term_rows)
        if not rows and search_terms:
            deep_clauses = []
            for term in search_terms[:3]:
                pattern = f"%{term}%"
                deep_clauses.extend([Tender.search_text.ilike(pattern), TenderSearchIndex.search_text.ilike(pattern)])
            rows = (
                db.query(Tender)
                .outerjoin(TenderSearchIndex, TenderSearchIndex.tender_id == Tender.id)
                .filter(Tender.is_active.is_(True))
                .filter(or_(*deep_clauses))
                .order_by(Tender.scraped_at.desc())
                .limit(250)
                .all()
            )
        if not rows:
            rows = (
                db.query(Tender)
                .filter(Tender.is_active.is_(True))
                .order_by(Tender.scraped_at.desc())
                .limit(300)
                .all()
            )
        state_filter = (state or intent.get("state") or "").lower()
        max_value_filter = max_value if max_value is not None else intent.get("max_value")
        closing_to_filter = closing_to or intent.get("closing_to")
        if portal:
            rows = [row for row in rows if portal.lower() in (row.portal or "").lower()]
        if state_filter:
            rows = [row for row in rows if state_filter in (row.state or "").lower() or state_filter in (row.location or "").lower()]
        if department:
            rows = [row for row in rows if department.lower() in (row.department or "").lower()]
        if category:
            rows = [
                row
                for row in rows
                if category.lower() in (row.ai_category or "").lower()
                or any(category.lower() in str(item).lower() for item in (row.categories or []))
            ]
        if organization:
            rows = [row for row in rows if organization.lower() in (row.organization or row.buyer or "").lower()]
        if tender_status:
            rows = [row for row in rows if tender_status.lower() in (row.tender_status or "").lower()]
        if min_value is not None:
            rows = [row for row in rows if row.estimated_value is not None and row.estimated_value >= min_value]
        if max_value_filter:
            rows = [row for row in rows if row.estimated_value is None or row.estimated_value <= max_value_filter]
        if published_from:
            rows = [row for row in rows if row.published_date and row.published_date >= published_from]
        if published_to:
            rows = [row for row in rows if row.published_date and row.published_date <= published_to]
        if closing_from:
            rows = [row for row in rows if row.closing_date and row.closing_date >= closing_from]
        if closing_to_filter:
            rows = [row for row in rows if row.closing_date and row.closing_date <= closing_to_filter]

        index_rows = {
            row.tender_id: row
            for row in db.query(TenderSearchIndex).filter(TenderSearchIndex.tender_id.in_([row.id for row in rows])).all()
        }
        scored = []
        similarity_threshold = settings()["ml_similarity_threshold"]
        for row in rows:
            if (row.title or "").strip().lower() in NON_TENDER_TITLES:
                continue
            raw = row.raw_data or {}
            ai = raw.get("ai") or {}
            index_row = index_rows.get(row.id)
            text = (index_row.search_text if index_row else None) or _row_search_blob(row)
            lexical, matched_terms = _lexical_score(q, expanded_terms, text)
            vector = ai.get("embedding") or (index_row.embedding if index_row else []) or []
            if not vector:
                semantic = cosine_similarity(query_vector, text_embedding(text)) if lexical >= 0.08 else 0.0
            else:
                semantic = cosine_similarity(query_vector, vector)
            recency = _recency_score(row)
            closing = _closing_score(row)
            value = _value_score(row)
            final_score = round(
                min(1.0, semantic * 0.48 + lexical * 0.32 + recency * 0.08 + closing * 0.08 + value * 0.04),
                4,
            )
            if matched_terms or lexical >= 0.08 or semantic >= similarity_threshold or final_score >= similarity_threshold:
                scored.append(
                    (
                        final_score,
                        row,
                        {
                            "semantic": round(semantic, 4),
                            "keyword": round(lexical, 4),
                            "recency": round(recency, 4),
                            "closing": round(closing, 4),
                            "value": round(value, 4),
                        },
                        matched_terms,
                        text,
                    )
                )

        ranked = sorted(scored, key=lambda item: (item[0], item[1].scraped_at), reverse=True)[:limit]
        payload = {
            "query": q,
            "intent": intent,
            "expanded_terms": expanded_terms,
            "highlight_terms": highlight_terms,
            "count": len(ranked),
            "results": [
                {
                    "id": tender.id,
                    "title": tender.title,
                    "snippet": _make_snippet(search_text, matched_terms or highlight_terms),
                    "matched_terms": matched_terms or highlight_terms[:4],
                    "portal": tender.portal,
                    "state": tender.state,
                    "department": tender.department,
                    "organization": tender.organization,
                    "closing_date": tender.closing_date,
                    "estimated_value": tender.estimated_value,
                    "ai_category": tender.ai_category or (index_rows.get(tender.id).ai_category if index_rows.get(tender.id) else None),
                    "ai_tags": ((tender.raw_data or {}).get("ai") or {}).get("tags") or (index_rows.get(tender.id).tags if index_rows.get(tender.id) else []) or tender.matched_keywords or [],
                    "ai_summary": ((tender.raw_data or {}).get("ai") or {}).get("summary") or (index_rows.get(tender.id).ai_summary if index_rows.get(tender.id) else None) or (tender.raw_data or {}).get("plain_summary"),
                    "confidence": round(score * 100),
                    "score": score,
                    "score_components": components,
                    "tender_status": tender.tender_status,
                }
                for score, tender, components, matched_terms, search_text in ranked
            ],
            "cached": False,
        }
        _SEARCH_CACHE[cache_key] = (time.time(), payload)
        return payload
    finally:
        db.close()


@router.get("/status")
def ml_status():
    from app.services.ml_engine import _load_model

    model = _load_model()
    return {"enabled": True, "loaded": model is not None, "status": "ready" if model else "fallback_to_fuzzy"}
