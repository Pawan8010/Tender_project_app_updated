import asyncio
import hashlib
import re
import threading
import time
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from app.config import settings
from app.keywords import analyze_tender_match, category_for_keyword, match_keywords
from app.models import Keyword, PortalRun, ProcurementPortal, ScrapeLog, Tender, TenderDocument, TenderHistory, TenderMatch, TenderChangeEvent
from app.notifier import alert_recipients_for_tender, send_alert_email
from app.services.backup import create_tender_backup
from app.services.summaries import plain_tender_summary
from app.services.change_detector import find_existing_tender, detect_and_log_changes


SCRAPE_LOCK = threading.Lock()
SCRAPER_RUNTIME = {
    "running": False,
    "last_started": None,
    "last_finished": None,
    "last_status": "idle",
    "last_error": None,
    "last_backup_error": None,
}

try:
    from scrapers.portals.gem import GeMScraper
    from scrapers.portals.cppp import CPPPScraper
    from scrapers.portals.gepnic import GePNICScraper
    from scrapers.portals.ireps import IREPSScraper
    from scrapers.portals.karnataka import KarnatakaScraper
    from scrapers.portals.andhra_pradesh import AndhraScraper
    from scrapers.portals.telangana import TelanganaScraper
    from scrapers.portals.gujarat import GujaratScraper
    from scrapers.portals.bihar import BiharScraper
    from scrapers.portals.nic_generic import NICGenericScraper

    PORTAL_SCRAPER_MAP = {
        "GeM": GeMScraper,
        "CPPP": CPPPScraper,
        "GePNIC": GePNICScraper,
        "IREPS": IREPSScraper,
        "Karnataka eProcurement": KarnatakaScraper,
        "Andhra Pradesh eProcurement": AndhraScraper,
        "Telangana Tenders": TelanganaScraper,
        "nProcure": GujaratScraper,
        "Bihar eProcurement": BiharScraper,
        
        "Defence eProcurement": NICGenericScraper,
        "Coal India Tenders": NICGenericScraper,
        "MahaTenders": NICGenericScraper,
        "Tamil Nadu Tenders": NICGenericScraper,
        "UP eTender": NICGenericScraper,
        "Rajasthan eProcurement": NICGenericScraper,
        "MP Tenders": NICGenericScraper,
        "Haryana eTenders": NICGenericScraper,
        "Punjab eProcurement": NICGenericScraper,
        "Kerala eTenders": NICGenericScraper,
        "West Bengal Tenders": NICGenericScraper,
        "Odisha Tenders": NICGenericScraper,
        "Jharkhand Tenders": NICGenericScraper,
        "Assam Tenders": NICGenericScraper,
    }
except ImportError:
    PORTAL_SCRAPER_MAP = {}


NIC_LATEST = "nicgep/app?page=FrontEndListTendersbyDate&service=page"
NIC_SEARCH = "nicgep/app?component=%24DirectLink&page=FrontEndAdvancedSearch&service=page"


def nic(domain: str):
    return [f"{domain}/{NIC_LATEST}"]


def clean_scrape_error(message: str) -> str:
    text = " ".join((message or "Portal scrape failed").split())
    text = re.sub(r"https?://\S+", "portal URL", text)
    replacements = [
        ("failed after retries:", "could not be reached:"),
        ("Client error '404 Not Found'", "Portal listing returned 404"),
        ("[Errno 11001] getaddrinfo failed", "DNS temporarily unavailable"),
        ("getaddrinfo failed", "DNS temporarily unavailable"),
        ("TimeoutError", "Portal timeout"),
        ("For more information check:", "Details:"),
    ]
    for old, new in replacements:
        text = text.replace(old, new)
    return text[:420]


def _portal_cache_count(db: Session, portal_name: str) -> int:
    return db.query(Tender).filter(Tender.portal == portal_name, Tender.is_active.is_(True)).count()


def _classify_scrape_failure(db: Session, portal_name: str, message: str) -> tuple[str, str]:
    lowered = message.lower()
    transient = any(
        marker in lowered
        for marker in [
            "403",
            "429",
            "503",
            "blocked",
            "timeout",
            "temporarily",
            "dns",
            "name or service",
            "could not be reached",
            "connection",
        ]
    )
    cached_count = _portal_cache_count(db, portal_name)
    if cached_count:
        return "cached", f"Portal temporarily unreachable; showing {cached_count} cached tenders. Next retry is scheduled automatically."
    if transient:
        return "retrying", "Portal temporarily unreachable; no cached tenders yet. Next retry is scheduled automatically."
    return "retrying", "Portal returned an unexpected response; scraper will retry automatically."


def scraper_runtime_status() -> dict:
    return {
        **SCRAPER_RUNTIME,
        "running": SCRAPE_LOCK.locked(),
        "portal_count": len(PORTALS),
        "interval_minutes": settings()["auto_scrape_interval_minutes"],
        "concurrency": settings()["scraper_concurrency"],
    }


def _push_scrape_event(message: str) -> None:
    try:
        from app.routers.scrape import push_log

        push_log(message)
    except Exception:
        pass


def _portal_defaults(name: str, url: str, state: str, use_playwright: bool, listing_urls: list[str]) -> dict:
    return {
        "name": name,
        "url": url,
        "state": state,
        "portal_type": "National" if state == "National" else "State",
        "authentication": "public",
        "scraper_type": "playwright" if use_playwright else "http",
        "scheduler": "interval",
        "retry_count": settings()["scraper_retries"],
        "health_status": "unknown",
        "proxy_configuration": {"proxy_enabled": settings()["use_proxy"]},
        "captcha_strategy": "detect_and_retry",
        "enabled": True,
        "listing_urls": listing_urls,
    }


def portal_browser_enabled(row: ProcurementPortal) -> bool:
    cfg = settings()
    return bool(cfg["use_playwright"] or cfg["scraper_force_playwright"]) and (
        cfg["scraper_force_playwright"] or row.scraper_type == "playwright"
    )


def sync_portal_registry(db: Session) -> None:
    now = datetime.utcnow()
    existing = {row.name: row for row in db.query(ProcurementPortal).all()}
    for name, url, state, use_playwright, listing_urls in PORTALS:
        defaults = _portal_defaults(name, url, state, use_playwright, listing_urls)
        row = existing.get(name)
        if row:
            row.url = row.url or defaults["url"]
            row.state = row.state or defaults["state"]
            row.portal_type = row.portal_type or defaults["portal_type"]
            row.scraper_type = row.scraper_type or defaults["scraper_type"]
            if defaults["scraper_type"] == "playwright" and row.scraper_type != "playwright":
                row.scraper_type = "playwright"
            row.listing_urls = row.listing_urls or defaults["listing_urls"]
            row.retry_count = row.retry_count or defaults["retry_count"]
            row.updated_at = now
        else:
            db.add(ProcurementPortal(**defaults))
    db.commit()


def _enabled_portal_rows(db: Session) -> list[ProcurementPortal]:
    sync_portal_registry(db)
    return db.query(ProcurementPortal).filter(ProcurementPortal.enabled.is_(True)).order_by(ProcurementPortal.name.asc()).all()


def _update_portal_health(db: Session, portal_name: str, status: str) -> None:
    row = db.query(ProcurementPortal).filter(ProcurementPortal.name == portal_name).first()
    if not row:
        return
    now = datetime.utcnow()
    healthy_statuses = {"success", "empty", "cached"}
    row.health_status = "online" if status in healthy_statuses else "degraded"
    if status in healthy_statuses:
        row.last_successful_run = now
    row.next_run = now + timedelta(minutes=settings()["auto_scrape_interval_minutes"])
    row.updated_at = now


def portal_catalog() -> list[dict]:
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        rows = _enabled_portal_rows(db)
        return [
            {
                "name": row.name,
                "url": row.url,
                "state": row.state,
                "kind": row.portal_type,
                "uses_playwright": portal_browser_enabled(row),
                "listing_urls": row.listing_urls or [row.url],
                "authentication": row.authentication,
                "scheduler": row.scheduler,
                "retry_count": row.retry_count,
                "health_status": row.health_status,
                "last_successful_run": row.last_successful_run,
                "next_run": row.next_run,
                "enabled": row.enabled,
                "captcha_strategy": row.captcha_strategy,
                "proxy_configuration": row.proxy_configuration or {},
            }
            for row in rows
        ]
    finally:
        db.close()


async def _scrape_with_limit(scraper, semaphore: asyncio.Semaphore, timeout: int):
    async with semaphore:
        return await asyncio.wait_for(scraper.scrape_all(), timeout=timeout)


def _upsert_tender(db: Session, tender_data: dict, return_changes: bool = False):
    started = time.perf_counter()
    tender_data = _normalize_tender_data(tender_data)
    
    tender_data["classification_status"] = tender_data.get("classification_status") or "PENDING_CLASSIFICATION"
    
    raw_data = dict(tender_data.get("raw_data") or {})
    raw_data["last_seen_at"] = datetime.utcnow().isoformat()
    raw_data["source"] = raw_data.get("source") or "live_portal"
    raw_data["plain_summary"] = plain_tender_summary({**tender_data, "raw_data": raw_data})
    tender_data["raw_data"] = raw_data

    existing = find_existing_tender(
        db,
        portal=tender_data.get("portal"),
        tender_id=tender_data.get("tender_id"),
        reference_number=tender_data.get("reference_number"),
        organization=tender_data.get("organization"),
        closing_date=tender_data.get("closing_date"),
        title=tender_data.get("title")
    )
    if existing:
        previous_hash = existing.content_hash
        change_type, changed_fields = detect_and_log_changes(db, existing, tender_data)
        
        if not changed_fields:
            # Duplicate/No content changes: preserve existing matching/alerting state
            tender_data["classification_status"] = existing.classification_status or "UNCLASSIFIED"
            tender_data["categories"] = existing.categories or []
            tender_data["matched_keywords"] = existing.matched_keywords or []
            tender_data["ai_category"] = existing.ai_category
            
            existing_raw = dict(existing.raw_data or {})
            merged_raw = dict(tender_data.get("raw_data") or {})
            for key in (
                "alerted_recipients", "alerted_at", "alert_attempted_at",
                "match_score", "match_aliases", "match_reasons",
                "semantic_matches", "ml_used"
            ):
                if key in existing_raw and key not in merged_raw:
                    merged_raw[key] = existing_raw[key]
            tender_data["raw_data"] = merged_raw
        else:
            # Actual content changed: reset classification status to trigger matching/alerting again
            tender_data["classification_status"] = "PENDING_CLASSIFICATION"
            tender_data["categories"] = []
            tender_data["matched_keywords"] = []
            tender_data["ai_category"] = None
            
        for field in (
            "title",
            "description",
            "portal",
            "state",
            "district",
            "department",
            "buyer",
            "organization",
            "location",
            "tender_url",
            "published_date",
            "closing_date",
            "estimated_value",
            "currency",
            "tender_status",
            "classification_status",
            "ai_category",
            "content_hash",
            "search_text",
            "bid_number",
            "reference_number",
            "categories",
            "matched_keywords",
            "raw_data",
        ):
            if field in tender_data:
                setattr(existing, field, tender_data.get(field))
        existing.is_active = True
        existing.updated_at = datetime.utcnow()
        existing.last_seen_at = datetime.utcnow()
        if changed_fields:
            db.add(
                TenderHistory(
                    tender=existing,
                    change_type=change_type,
                    previous_hash=previous_hash,
                    new_hash=tender_data.get("content_hash"),
                    changed_fields=changed_fields,
                    snapshot=_tender_snapshot(existing),
                )
            )
            db.add(
                TenderChangeEvent(
                    tender_id=existing.id,
                    change_type=change_type,
                    changed_fields=changed_fields,
                    snapshot=_tender_snapshot(existing),
                )
            )
        _queue_documents(db, existing, tender_data)
        try:
            from app.services.tender_index import index_tender

            index_tender(db, existing)
        except Exception:
            pass
        status = "updated" if changed_fields else "duplicate"
        if return_changes:
            return status, existing.id, changed_fields
        return status

    tender = Tender(**tender_data)
    db.add(tender)
    db.flush()
    db.add(
        TenderHistory(
            tender=tender,
            change_type="New Tender",
            previous_hash=None,
            new_hash=tender.content_hash,
            changed_fields={},
            snapshot=_tender_snapshot(tender),
        )
    )
    db.add(
        TenderChangeEvent(
            tender_id=tender.id,
            change_type="New Tender",
            changed_fields={},
            snapshot=_tender_snapshot(tender),
        )
    )
    _queue_documents(db, tender, tender_data)
    try:
        from app.services.tender_index import index_tender

        index_tender(db, tender)
    except Exception:
        pass
    if return_changes:
        return "new", tender.id, {}
    return "created"


def _content_hash(payload: dict) -> str:
    stable = {
        key: payload.get(key)
        for key in (
            "tender_id",
            "bid_number",
            "reference_number",
            "title",
            "description",
            "portal",
            "state",
            "department",
            "buyer",
            "organization",
            "closing_date",
            "estimated_value",
            "tender_url",
        )
    }
    return hashlib.sha256(json_safe(stable).encode("utf-8")).hexdigest()


def json_safe(payload: dict) -> str:
    import json

    return json.dumps(payload, sort_keys=True, default=str, ensure_ascii=False)


def _raw_value(raw_data: dict, *keys: str):
    for key in keys:
        value = raw_data.get(key)
        if value not in (None, ""):
            return str(value)
    return None


def _normalize_tender_data(tender_data: dict) -> dict:
    raw_data = dict(tender_data.get("raw_data") or {})
    normalized = dict(tender_data)
    normalized["raw_data"] = raw_data
    normalized["bid_number"] = normalized.get("bid_number") or _raw_value(raw_data, "bid_number", "bid_no", "tender_display_id", "procurement_id")
    normalized["reference_number"] = normalized.get("reference_number") or _raw_value(raw_data, "reference_number", "reference_no", "tender_number", "nit_id")
    normalized["district"] = normalized.get("district") or _raw_value(raw_data, "district")
    normalized["department"] = normalized.get("department") or _raw_value(raw_data, "department", "ministry")
    normalized["buyer"] = normalized.get("buyer") or _raw_value(raw_data, "buyer", "contact_person")
    normalized["organization"] = normalized.get("organization") or _raw_value(raw_data, "organization", "organisation")
    normalized["location"] = normalized.get("location") or _raw_value(raw_data, "location", "office")
    normalized["currency"] = normalized.get("currency") or "INR"
    normalized["tender_status"] = normalized.get("tender_status") or _raw_value(raw_data, "tender_status", "status") or "ACTIVE"
    normalized["scraped_at"] = normalized.get("scraped_at") or datetime.utcnow()
    normalized["updated_at"] = datetime.utcnow()
    normalized["last_seen_at"] = datetime.utcnow()
    normalized["search_text"] = " ".join(
        str(part)
        for part in [
            normalized.get("title"),
            normalized.get("description"),
            normalized.get("portal"),
            normalized.get("state"),
            normalized.get("district"),
            normalized.get("department"),
            normalized.get("buyer"),
            normalized.get("organization"),
            normalized.get("bid_number"),
            normalized.get("reference_number"),
            raw_data.get("pdf_text"),
            raw_data.get("ocr_text"),
            " ".join(raw_data.get("items") or []) if isinstance(raw_data.get("items"), list) else raw_data.get("items"),
        ]
        if part
    )
    normalized["content_hash"] = _content_hash(normalized)
    return normalized


def _find_existing_tender(db: Session, tender_data: dict) -> Tender | None:
    tender_id = tender_data.get("tender_id")
    if tender_id:
        existing = db.query(Tender).filter(Tender.tender_id == tender_id).first()
        if existing:
            return existing
    portal = tender_data.get("portal")
    for field in ("bid_number", "reference_number", "content_hash"):
        value = tender_data.get(field)
        if value:
            existing = db.query(Tender).filter(Tender.portal == portal, getattr(Tender, field) == value).first()
            if existing:
                return existing
    tender_url = tender_data.get("tender_url")
    raw_data = tender_data.get("raw_data") or {}
    source_url = raw_data.get("source_url")
    stable_url = raw_data.get("stable_url")
    url_is_detail = tender_url and tender_url not in {source_url, stable_url} and any(
        marker in str(tender_url).lower()
        for marker in ("detail", "view", "showbid", "download", "directlink", "nit", "bid")
    )
    if url_is_detail:
        existing = db.query(Tender).filter(Tender.portal == portal, Tender.tender_url == tender_url).first()
        if existing:
            return existing
    return None


def _changed_fields(existing: Tender, incoming: dict) -> dict:
    changes = {}
    for field in (
        "title",
        "description",
        "closing_date",
        "estimated_value",
        "tender_status",
        "content_hash",
        "bid_number",
        "reference_number",
    ):
        old = getattr(existing, field, None)
        new = incoming.get(field)
        if str(old or "") != str(new or ""):
            changes[field] = {"old": _json_ready(old), "new": _json_ready(new)}
    return changes


def _tender_snapshot(tender: Tender) -> dict:
    return _json_ready({
        "tender_id": tender.tender_id,
        "title": tender.title,
        "portal": tender.portal,
        "state": tender.state,
        "closing_date": tender.closing_date,
        "estimated_value": tender.estimated_value,
        "categories": tender.categories or [],
        "matched_keywords": tender.matched_keywords or [],
        "raw_data": tender.raw_data or {},
    })


def _json_ready(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _json_ready(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_ready(item) for item in value]
    if isinstance(value, tuple):
        return [_json_ready(item) for item in value]
    return value


def _document_urls(tender_data: dict) -> list[str]:
    raw_data = tender_data.get("raw_data") or {}
    urls = []
    for key in ("attachments", "attachment_urls", "pdf_urls", "document_urls", "boq_urls"):
        value = raw_data.get(key)
        if isinstance(value, list):
            urls.extend(str(item) for item in value if item)
        elif isinstance(value, str) and value.startswith(("http://", "https://")):
            urls.append(value)
    tender_url = tender_data.get("tender_url")
    if tender_url and str(tender_url).lower().endswith((".pdf", ".doc", ".docx", ".xls", ".xlsx", ".zip", ".rar")):
        urls.append(tender_url)
    return list(dict.fromkeys(urls))


def _queue_documents(db: Session, tender: Tender, tender_data: dict) -> None:
    for url in _document_urls(tender_data):
        exists = db.query(TenderDocument.id).filter(TenderDocument.tender_id == tender.id, TenderDocument.url == url).first()
        if exists:
            continue
        file_name = url.rsplit("/", 1)[-1].split("?", 1)[0][:255] or None
        db.add(TenderDocument(tender=tender, url=url, file_name=file_name, status="queued"))





PORTALS = [
    ("GeM", "https://bidplus.gem.gov.in/all-bids", "National", True, ["https://bidplus.gem.gov.in/all-bids"]),
    ("CPPP", "https://eprocure.gov.in/eprocure/app", "National", False, ["https://eprocure.gov.in/eprocure/app?page=FrontEndListTendersbyDate&service=page"]),
    (
        "GePNIC",
        "https://gepnic.gov.in",
        "National",
        True,
        [
            "https://gepnic.gov.in/Tender/TenderList.aspx",
            "https://gepnic.gov.in/Tender/tender_list.aspx",
            "https://gepnic.gov.in",
        ],
    ),
    ("IREPS", "https://www.ireps.gov.in", "National", True, ["https://www.ireps.gov.in/epsn/guestLogin.do"]),
    ("Defence eProcurement", "https://defproc.gov.in", "National", False, nic("https://defproc.gov.in")),
    ("Coal India Tenders", "https://coalindiatenders.nic.in", "National", False, nic("https://coalindiatenders.nic.in")),
    ("MahaTenders", "https://mahatenders.gov.in", "Maharashtra", False, nic("https://mahatenders.gov.in")),
    (
        "nProcure",
        "https://tender.nprocure.com",
        "Gujarat",
        True,
        ["https://tender.nprocure.com/dashboard/getTenderClosingData", "https://tender.nprocure.com"],
    ),
    (
        "Karnataka eProcurement",
        "https://eproc.karnataka.gov.in",
        "Karnataka",
        True,
        ["https://kppp.karnataka.gov.in/", "https://eproc.karnataka.gov.in"],
    ),
    ("Tamil Nadu Tenders", "https://tntenders.gov.in", "Tamil Nadu", False, nic("https://tntenders.gov.in")),
    (
        "Telangana Tenders",
        "https://tender.telangana.gov.in",
        "Telangana",
        True,
        ["https://tender.telangana.gov.in/login.html", "https://tender.telangana.gov.in/Home/LatestTender"],
    ),
    ("Andhra Pradesh eProcurement", "https://tender.apeprocurement.gov.in", "Andhra Pradesh", True, ["https://tender.apeprocurement.gov.in/login.html"]),
    ("UP eTender", "https://etender.up.nic.in", "Uttar Pradesh", False, nic("https://etender.up.nic.in")),
    ("Rajasthan eProcurement", "https://eproc.rajasthan.gov.in", "Rajasthan", False, nic("https://eproc.rajasthan.gov.in")),
    ("MP Tenders", "https://mptenders.gov.in", "Madhya Pradesh", False, nic("https://mptenders.gov.in")),
    ("Haryana eTenders", "https://etenders.hry.nic.in", "Haryana", False, nic("https://etenders.hry.nic.in")),
    ("Punjab eProcurement", "https://eproc.punjab.gov.in", "Punjab", False, nic("https://eproc.punjab.gov.in")),
    ("Kerala eTenders", "https://etenders.kerala.gov.in", "Kerala", False, nic("https://etenders.kerala.gov.in")),
    ("West Bengal Tenders", "https://wbtenders.gov.in", "West Bengal", False, nic("https://wbtenders.gov.in")),
    ("Odisha Tenders", "https://tendersodisha.gov.in", "Odisha", False, nic("https://tendersodisha.gov.in")),
    (
        "Bihar eProcurement",
        "https://eproc2.bihar.gov.in",
        "Bihar",
        True,
        [
            "https://eproc2.bihar.gov.in/EPSV2Web/openarea/tenderListingPage.action",
            "https://eproc2.bihar.gov.in/EPSV2Web/openarea/openTenderAction.action",
        ],
    ),
    ("Jharkhand Tenders", "https://jharkhandtenders.gov.in", "Jharkhand", False, nic("https://jharkhandtenders.gov.in")),
    ("Assam Tenders", "https://assamtenders.gov.in", "Assam", False, nic("https://assamtenders.gov.in")),
]


def all_scrapers(db: Session | None = None):
    if db is None:
        from app.database import SessionLocal

        local_db = SessionLocal()
        try:
            return all_scrapers(local_db)
        finally:
            local_db.close()
    from scrapers.portals.gem import GeMScraper
    from scrapers.portals.cppp import CPPPScraper
    from scrapers.portals.gepnic import GePNICScraper
    from scrapers.portals.ireps import IREPSScraper
    from scrapers.portals.karnataka import KarnatakaScraper
    from scrapers.portals.andhra_pradesh import AndhraScraper
    from scrapers.portals.telangana import TelanganaScraper
    from scrapers.portals.gujarat import GujaratScraper
    from scrapers.portals.bihar import BiharScraper
    from scrapers.portals.nic_generic import NICGenericScraper

    PORTAL_SCRAPER_MAP = {
        "GeM": GeMScraper,
        "CPPP": CPPPScraper,
        "GePNIC": GePNICScraper,
        "IREPS": IREPSScraper,
        "Karnataka eProcurement": KarnatakaScraper,
        "Andhra Pradesh eProcurement": AndhraScraper,
        "Telangana Tenders": TelanganaScraper,
        "nProcure": GujaratScraper,
        "Bihar eProcurement": BiharScraper,
    }

    scrapers = []
    for row in _enabled_portal_rows(db):
        try:
            scraper_class = PORTAL_SCRAPER_MAP.get(row.name, NICGenericScraper)
            scraper_instance = scraper_class(
                portal_name=row.name,
                base_url=row.url,
                state=row.state or "National",
                use_playwright=portal_browser_enabled(row),
                listing_urls=row.listing_urls or [row.url],
            )
            scrapers.append(scraper_instance)
        except Exception as e:
            print(f"Failed to load scraper for {row.name}: {e}")
            
    return scrapers


async def run_all_scrapers(db: Session) -> dict:
    if not SCRAPE_LOCK.acquire(blocking=False):
        return {"status": "already_running", "portals": len(PORTALS), "tenders_found": 0, "updated_tenders": 0, "logs": []}

    try:
        SCRAPER_RUNTIME.update(
            {
                "running": True,
                "last_started": datetime.utcnow(),
                "last_finished": None,
                "last_status": "running",
                "last_error": None,
            }
        )
        scrapers = all_scrapers(db)
        _push_scrape_event(f"Started live scrape for {len(scrapers)} portals")
        cfg = settings()
        timeout = cfg["scraper_portal_timeout_seconds"]
        semaphore = asyncio.Semaphore(cfg["scraper_concurrency"])
        
        # End the current transaction before long-running network requests
        db.commit()
        
        results = await asyncio.gather(*(_scrape_with_limit(scraper, semaphore, timeout) for scraper in scrapers), return_exceptions=True)
        logs = []
        total_new = 0
        total_updated = 0

        for scraper, result in zip(scrapers, results):
            run_started = datetime.utcnow()
            portal_run = PortalRun(portal=scraper.portal_name, status="running", started_at=run_started)
            db.add(portal_run)
            db.flush()
            if isinstance(result, Exception):
                message = clean_scrape_error(str(result) or result.__class__.__name__)
                status, friendly_message = _classify_scrape_failure(db, scraper.portal_name, message)
                log = ScrapeLog(portal=scraper.portal_name, status=status, tenders_found=0, error_message=friendly_message)
                db.add(log)
                portal_run.status = status
                portal_run.finished_at = datetime.utcnow()
                portal_run.error_message = friendly_message
                portal_run.failed_count = 1
                _update_portal_health(db, scraper.portal_name, status)
                logs.append({"portal": scraper.portal_name, "status": status, "error": friendly_message, "tenders_found": 0})
                _push_scrape_event(f"{scraper.portal_name}: {status} - {friendly_message}")
                continue

            new_count = 0
            updated_count = 0
            duplicate_count = 0
            for tender_data in result:
                action = _upsert_tender(db, tender_data)
                if action == "created":
                    new_count += 1
                    total_new += 1
                elif action == "updated":
                    updated_count += 1
                    total_updated += 1
                elif action == "duplicate":
                    duplicate_count += 1

            status = "success" if result else "empty"
            db.add(ScrapeLog(portal=scraper.portal_name, status=status, tenders_found=new_count))
            portal_run.status = status
            portal_run.finished_at = datetime.utcnow()
            portal_run.fetched_count = len(result)
            portal_run.stored_count = new_count
            portal_run.updated_count = updated_count
            portal_run.duplicate_count = duplicate_count
            portal_run.logs = [{"message": f"{new_count} new, {updated_count} updated, {duplicate_count} duplicates"}]
            _update_portal_health(db, scraper.portal_name, status)
            logs.append({"portal": scraper.portal_name, "status": status, "tenders_found": new_count, "updated_tenders": updated_count})
            _push_scrape_event(f"{scraper.portal_name}: {status}, {new_count} new, {updated_count} refreshed")

        db.commit()
        backup_summary = None
        if cfg["backup_enabled"]:
            try:
                backup = create_tender_backup(db, backup_type="matched", reason="auto-scrape")
                backup_summary = {
                    "id": backup.id,
                    "file_name": backup.file_name,
                    "tender_count": backup.tender_count,
                    "matched_count": backup.matched_count,
                    "created_at": backup.created_at,
                }
                SCRAPER_RUNTIME["last_backup_error"] = None
            except Exception as exc:
                SCRAPER_RUNTIME["last_backup_error"] = str(exc)

        run_status = "degraded" if any(log["status"] in {"failed", "retrying", "temporarily_blocked"} for log in logs) else "ok"
        SCRAPER_RUNTIME.update(
            {
                "running": False,
                "last_finished": datetime.utcnow(),
                "last_status": run_status,
                "last_error": None,
            }
        )
        _push_scrape_event(f"Scrape cycle finished: {run_status}, {total_new} new, {total_updated} refreshed")
        return {"status": run_status, "portals": len(scrapers), "tenders_found": total_new, "updated_tenders": total_updated, "logs": logs, "backup": backup_summary}
    except Exception as exc:
        db.rollback()
        message = clean_scrape_error(str(exc) or exc.__class__.__name__)
        SCRAPER_RUNTIME.update(
            {
                "running": False,
                "last_finished": datetime.utcnow(),
                "last_status": "failed",
                "last_error": message,
            }
        )
        _push_scrape_event(f"Scrape cycle failed: {message}")
        raise
    finally:
        SCRAPE_LOCK.release()


async def run_one_scraper(db: Session, portal_name: str) -> dict:
    selected = next((scraper for scraper in all_scrapers(db) if scraper.portal_name.lower() == portal_name.lower()), None)
    if not selected:
        return {"status": "not_found", "portal": portal_name, "tenders_found": 0, "error": "Portal not found"}

    if not SCRAPE_LOCK.acquire(blocking=False):
        return {"status": "already_running", "portal": selected.portal_name, "tenders_found": 0, "updated_tenders": 0}

    try:
        SCRAPER_RUNTIME.update(
            {
                "running": True,
                "last_started": datetime.utcnow(),
                "last_finished": None,
                "last_status": "running",
                "last_error": None,
            }
        )
        try:
            _push_scrape_event(f"Started {selected.portal_name} scrape")
            portal_run = PortalRun(portal=selected.portal_name, status="running", started_at=datetime.utcnow())
            db.add(portal_run)
            db.commit() # Commit before long-running scrape
            
            result = await asyncio.wait_for(selected.scrape_all(), timeout=settings()["scraper_portal_timeout_seconds"])
        except Exception as exc:
            message = clean_scrape_error(str(exc) or exc.__class__.__name__)
            status, friendly_message = _classify_scrape_failure(db, selected.portal_name, message)
            db.add(ScrapeLog(portal=selected.portal_name, status=status, tenders_found=0, error_message=friendly_message))
            db.add(
                PortalRun(
                    portal=selected.portal_name,
                    status=status,
                    started_at=datetime.utcnow(),
                    finished_at=datetime.utcnow(),
                    failed_count=1,
                    error_message=friendly_message,
                )
            )
            _update_portal_health(db, selected.portal_name, status)
            db.commit()
            SCRAPER_RUNTIME.update(
                {
                    "running": False,
                    "last_finished": datetime.utcnow(),
                    "last_status": status,
                    "last_error": friendly_message,
                }
            )
            return {"status": status, "portal": selected.portal_name, "tenders_found": 0, "updated_tenders": 0, "error": friendly_message}

        new_count = 0
        updated_count = 0
        duplicate_count = 0
        for tender_data in result:
            action = _upsert_tender(db, tender_data)
            if action == "created":
                new_count += 1
            elif action == "updated":
                updated_count += 1
            elif action == "duplicate":
                duplicate_count += 1

        status = "success" if result else "empty"
        db.add(ScrapeLog(portal=selected.portal_name, status=status, tenders_found=new_count))
        portal_run.status = status
        portal_run.finished_at = datetime.utcnow()
        portal_run.fetched_count = len(result)
        portal_run.stored_count = new_count
        portal_run.updated_count = updated_count
        portal_run.duplicate_count = duplicate_count
        portal_run.logs = [{"message": f"{new_count} new, {updated_count} updated, {duplicate_count} duplicates"}]
        _update_portal_health(db, selected.portal_name, status)
        db.commit()
        _push_scrape_event(f"{selected.portal_name}: {status}, {new_count} new, {updated_count} refreshed")
        backup_summary = None
        if settings()["backup_enabled"]:
            try:
                backup = create_tender_backup(db, backup_type="matched", reason=f"portal-{selected.portal_name}")
                backup_summary = {
                    "id": backup.id,
                    "file_name": backup.file_name,
                    "tender_count": backup.tender_count,
                    "matched_count": backup.matched_count,
                    "created_at": backup.created_at,
                }
                SCRAPER_RUNTIME["last_backup_error"] = None
            except Exception as exc:
                SCRAPER_RUNTIME["last_backup_error"] = str(exc)

        SCRAPER_RUNTIME.update(
            {
                "running": False,
                "last_finished": datetime.utcnow(),
                "last_status": status,
                "last_error": None,
            }
        )
        _push_scrape_event(f"{selected.portal_name}: scrape finished, {new_count} new, {updated_count} refreshed")
        return {"status": status, "portal": selected.portal_name, "tenders_found": new_count, "updated_tenders": updated_count, "backup": backup_summary}
    except Exception as exc:
        db.rollback()
        message = clean_scrape_error(str(exc) or exc.__class__.__name__)
        SCRAPER_RUNTIME.update(
            {
                "running": False,
                "last_finished": datetime.utcnow(),
                "last_status": "failed",
                "last_error": message,
            }
        )
        return {"status": "failed", "portal": selected.portal_name, "tenders_found": 0, "updated_tenders": 0, "error": message}
    finally:
        SCRAPE_LOCK.release()


def run_all_scrapers_sync() -> dict:
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        return asyncio.run(run_all_scrapers(db))
    finally:
        db.close()


def run_one_scraper_sync(portal_name: str) -> dict:
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        return asyncio.run(run_one_scraper(db, portal_name))
    finally:
        db.close()


def _record_matches(db: Session, tender, match_meta: dict, started: float):
    processing_time_ms = int((time.perf_counter() - started) * 1000)
    cats_list = match_meta.get("categories") or [None]
    score = int(match_meta.get("match_score") or 0)
    reasons = match_meta.get("match_reasons") or []

    keywords = match_meta.get("matched_keywords") or ["AI Classification"]
    for keyword in keywords:
        category = cats_list[0] if cats_list else None

        exists = db.query(TenderMatch).filter(
            TenderMatch.tender_id == tender.id,
            TenderMatch.matched_keyword == keyword,
            TenderMatch.category == category
        ).first()

        if exists:
            exists.confidence = min(1.0, max(0.0, score / 100))
            exists.score = score
            exists.reason = "; ".join(reasons[:3])[:1000] if reasons else None
            exists.processing_time_ms = processing_time_ms
        else:
            db.add(
                TenderMatch(
                    tender_id=tender.id,
                    matched_keyword=keyword,
                    category=category,
                    confidence=min(1.0, max(0.0, score / 100)),
                    reason="; ".join(reasons[:3])[:1000] if reasons else None,
                    score=score,
                    matching_fields=["title", "description", "metadata"],
                    processing_time_ms=processing_time_ms,
                )
            )
