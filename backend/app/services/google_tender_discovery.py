import asyncio
import time
from dataclasses import dataclass
from datetime import date
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import httpx
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.models import Tender
from scrapers.registry import PORTAL_SCRAPER_MAP, _upsert_tender, portal_catalog, sync_portal_registry
from scrapers.portals.nic_generic import NICGenericScraper


@dataclass
class DiscoveryCandidate:
    portal_name: str
    portal_url: str
    state: str
    query: str
    title: str
    url: str
    snippet: str
    display_link: str


_DISCOVERY_CACHE: dict[tuple[str, int], tuple[float, dict]] = {}
_CACHE_TTL_SECONDS = 300


def _root_search_domain(host: str) -> str:
    host = (host or "").lower().strip()
    if host.startswith("www."):
        host = host[4:]
    parts = host.split(".")
    if len(parts) >= 3 and parts[-2:] == ["gov", "in"]:
        return ".".join(parts[-3:])
    if len(parts) >= 3 and parts[-2:] == ["nic", "in"]:
        return ".".join(parts[-3:])
    return host


def _canonical_url(url: str) -> str:
    parsed = urlparse(url)
    query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.lower().startswith("utm_") and key.lower() not in {"gclid", "fbclid"}
    ]
    return urlunparse(
        (
            parsed.scheme.lower() or "https",
            parsed.netloc.lower(),
            parsed.path,
            "",
            urlencode(query, doseq=True),
            "",
        )
    )


def _portal_domains(portal: dict) -> set[str]:
    domains = set()
    for url in [portal.get("url"), *(portal.get("listing_urls") or [])]:
        host = urlparse(url or "").netloc.lower()
        if host:
            domains.add(host[4:] if host.startswith("www.") else host)
            domains.add(_root_search_domain(host))
    return {domain for domain in domains if domain}


def _host_allowed(url: str, domains: set[str]) -> bool:
    host = urlparse(url).netloc.lower()
    host = host[4:] if host.startswith("www.") else host
    return any(host == domain or host.endswith(f".{domain}") for domain in domains)


def _google_configured() -> bool:
    cfg = settings()
    return bool(cfg.get("google_search_api_key") and cfg.get("google_search_cx"))


def configured_portal_queries(limit_portals: int | None = None) -> list[dict]:
    db = SessionLocal()
    try:
        sync_portal_registry(db)
    finally:
        db.close()

    queries: list[dict] = []
    for portal in portal_catalog():
        domains = sorted(_portal_domains(portal))
        if not domains:
            continue
        primary_domain = domains[0]
        queries.append(
            {
                "portal": portal["name"],
                "state": portal.get("state") or "National",
                "portal_url": portal.get("url"),
                "domain": primary_domain,
                "query": f"site:{primary_domain} tender",
                "allowed_domains": domains,
            }
        )
        if limit_portals and len(queries) >= limit_portals:
            break
    return queries


async def _google_query(client: httpx.AsyncClient, query: dict, limit: int) -> list[DiscoveryCandidate]:
    cfg = settings()
    response = await client.get(
        "https://www.googleapis.com/customsearch/v1",
        params={
            "key": cfg["google_search_api_key"],
            "cx": cfg["google_search_cx"],
            "q": query["query"],
            "num": min(max(limit, 1), 10),
            "safe": "off",
        },
    )
    response.raise_for_status()
    items = response.json().get("items", [])
    candidates: list[DiscoveryCandidate] = []
    for item in items:
        link = _canonical_url(item.get("link") or "")
        if not link or not _host_allowed(link, set(query["allowed_domains"])):
            continue
        candidates.append(
            DiscoveryCandidate(
                portal_name=query["portal"],
                portal_url=query.get("portal_url") or "",
                state=query.get("state") or "National",
                query=query["query"],
                title=item.get("title") or "Google discovered tender",
                url=link,
                snippet=item.get("snippet") or "",
                display_link=item.get("displayLink") or "",
            )
        )
    return candidates


async def discover_google_tenders(
    limit_per_portal: int | None = None,
    max_portals: int | None = None,
    store: bool = True,
) -> dict:
    cfg = settings()
    limit = limit_per_portal or cfg.get("google_discovery_limit_per_portal", 3)
    cache_key = (f"{max_portals or 0}:{store}", limit)
    cached = _DISCOVERY_CACHE.get(cache_key)
    if cached and time.time() - cached[0] < _CACHE_TTL_SECONDS:
        return {**cached[1], "cached": True}

    queries = configured_portal_queries(max_portals)
    if not _google_configured():
        return {
            "configured": False,
            "status": "not_configured",
            "queries": queries,
            "discovered": 0,
            "stored": 0,
            "new": 0,
            "updated": 0,
            "duplicates": 0,
            "failed": 0,
            "results": [],
            "message": "Google Programmable Search keys are required: GOOGLE_SEARCH_API_KEY and GOOGLE_SEARCH_CX.",
        }

    semaphore = asyncio.Semaphore(cfg.get("google_discovery_concurrency", 4))
    timeout = cfg.get("scraper_request_timeout_seconds", 12)

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        async def run_query(query: dict):
            async with semaphore:
                try:
                    return await _google_query(client, query, limit)
                except Exception as exc:
                    return {"query": query, "error": str(exc)[:240]}

        query_results = await asyncio.gather(*(run_query(query) for query in queries))

    errors = [item for item in query_results if isinstance(item, dict)]
    candidates: list[DiscoveryCandidate] = []
    seen_urls: set[str] = set()
    for result in query_results:
        if isinstance(result, dict):
            continue
        for candidate in result:
            if candidate.url in seen_urls:
                continue
            seen_urls.add(candidate.url)
            candidates.append(candidate)

    if not store:
        payload = {
            "configured": True,
            "status": "discovered",
            "queries": queries,
            "discovered": len(candidates),
            "stored": 0,
            "new": 0,
            "updated": 0,
            "duplicates": 0,
            "failed": len(errors),
            "errors": errors,
            "results": [candidate.__dict__ for candidate in candidates],
        }
        _DISCOVERY_CACHE[cache_key] = (time.time(), payload)
        return payload

    scraper_cache = {}
    stored_results = []
    counts = {"stored": 0, "new": 0, "updated": 0, "duplicates": 0, "failed": 0}

    async def extract_candidate(candidate: DiscoveryCandidate):
        scraper = scraper_cache.get(candidate.portal_name)
        if scraper is None:
            scraper_class = PORTAL_SCRAPER_MAP.get(candidate.portal_name, NICGenericScraper)
            scraper = scraper_class(
                portal_name=candidate.portal_name,
                base_url=candidate.portal_url,
                state=candidate.state,
                use_playwright=False,
                listing_urls=[candidate.portal_url] if candidate.portal_url else [],
            )
            scraper_cache[candidate.portal_name] = scraper
        try:
            return await scraper.extract_tender_from_url(
                candidate.url,
                title_hint=candidate.title,
                description_hint=candidate.snippet,
                discovery_context={
                    "engine": "google_programmable_search",
                    "query": candidate.query,
                    "display_link": candidate.display_link,
                    "portal_url": candidate.portal_url,
                    "discovered_at": date.today().isoformat(),
                },
            )
        except Exception as exc:
            return {
                "tender_id": scraper.generate_tender_id(candidate.title, candidate.url),
                "title": candidate.title[:500],
                "description": candidate.snippet or candidate.title,
                "portal": candidate.portal_name,
                "state": candidate.state,
                "tender_url": candidate.url,
                "published_date": date.today(),
                "closing_date": None,
                "estimated_value": None,
                "categories": ["Google Discovery"],
                "matched_keywords": [],
                "classification_status": "PENDING_CLASSIFICATION",
                "raw_data": {
                    "source": "google_discovery",
                    "source_url": candidate.portal_url,
                    "stable_url": candidate.url,
                    "scrape_method": "google_discovery_placeholder",
                    "detail_enrichment_status": "failed",
                    "detail_enrichment_error": str(exc)[:240],
                    "discovery": {
                        "engine": "google_programmable_search",
                        "query": candidate.query,
                        "display_link": candidate.display_link,
                    },
                },
            }

    extraction_semaphore = asyncio.Semaphore(cfg.get("google_discovery_concurrency", 4))

    async def guarded_extract(candidate: DiscoveryCandidate):
        async with extraction_semaphore:
            return candidate, await extract_candidate(candidate)

    extracted = await asyncio.gather(*(guarded_extract(candidate) for candidate in candidates), return_exceptions=True)

    db: Session = SessionLocal()
    try:
        existing_urls = {
            row.tender_url
            for row in db.query(Tender.tender_url).filter(Tender.tender_url.in_([candidate.url for candidate in candidates])).all()
            if row.tender_url
        }
        for item in extracted:
            if isinstance(item, Exception):
                counts["failed"] += 1
                continue
            candidate, tender_data = item
            status, tender_id, changes = _upsert_tender(db, tender_data, return_changes=True)
            db.commit()
            if status in {"new", "created"}:
                counts["new"] += 1
            elif status == "updated":
                counts["updated"] += 1
            else:
                counts["duplicates"] += 1
            counts["stored"] += 1
            stored_results.append(
                {
                    "id": tender_id,
                    "status": status,
                    "portal": candidate.portal_name,
                    "title": tender_data.get("title"),
                    "url": candidate.url,
                    "query": candidate.query,
                    "already_seen": candidate.url in existing_urls,
                    "changed_fields": changes,
                }
            )
    finally:
        db.close()

    payload = {
        "configured": True,
        "cached": False,
        "status": "stored",
        "queries": queries,
        "discovered": len(candidates),
        "stored": counts["stored"],
        "new": counts["new"],
        "updated": counts["updated"],
        "duplicates": counts["duplicates"],
        "failed": counts["failed"] + len(errors),
        "errors": errors,
        "results": stored_results,
        "message": (
            f"Google discovery checked {len(queries)} portal queries, found {len(candidates)} URLs, "
            f"stored {counts['stored']} records."
        ),
    }
    _DISCOVERY_CACHE[cache_key] = (time.time(), payload)
    return payload
