import asyncio
import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.auth import get_current_user, token_payload
from app.database import get_db
from app.database import SessionLocal
from app.models import PortalRun, ProcurementPortal, ScrapeLog, Tender, TenderDocument, User
from app.services.document_processor import process_queued_documents
from app.schemas import CleanupOut, PortalOut, PortalRunOut, PortalUpdate, ScrapeLogOut, ScrapeRunOut
from scrapers.registry import run_all_scrapers_sync, run_one_scraper_sync, scraper_runtime_status, sync_portal_registry

router = APIRouter()
_scrape_log: list[dict] = []
_background_scrape_tasks: set[asyncio.Task] = set()


def push_log(message: str):
    _scrape_log.append({"message": message, "at": datetime.utcnow().isoformat()})
    if len(_scrape_log) > 200:
        del _scrape_log[:-200]


@router.post("/run", response_model=ScrapeRunOut)
async def run_scrape(_user=Depends(get_current_user)):
    return await asyncio.to_thread(run_all_scrapers_sync)


@router.post("/start")
async def start_scrape(_user=Depends(get_current_user)):
    status = scraper_runtime_status()
    if status["running"]:
        push_log("Manual live scrape requested while another scrape is already running")
        return {
            "status": "already_running",
            "portals": status["portal_count"],
            "tenders_found": 0,
            "updated_tenders": 0,
            "message": "Scraper is already running. Watch the live stream for portal updates.",
        }

    push_log("Manual live scrape started in background")
    task = asyncio.create_task(asyncio.to_thread(run_all_scrapers_sync))
    _background_scrape_tasks.add(task)

    def cleanup(done_task: asyncio.Task) -> None:
        _background_scrape_tasks.discard(done_task)
        try:
            done_task.result()
        except Exception as exc:
            push_log(f"Background scrape failed: {str(exc)[:180]}")

    task.add_done_callback(cleanup)
    return {
        "status": "started",
        "portals": status["portal_count"],
        "tenders_found": 0,
        "updated_tenders": 0,
        "message": "Live scraper started. Portal results will stream into the dashboard.",
    }


def _search_terms(search: str) -> list[str]:
    return [term.lower() for term in str(search or "").split() if len(term) >= 3]


SEARCH_GENERIC_TERMS = {
    "long", "range", "supply", "work", "works", "service", "services",
    "procurement", "purchase", "tender", "bid", "rfq", "rfp", "open",
}
SEARCH_DOMAIN_TERMS = {
    "thermal", "imaging", "camera", "cctv", "ptz", "surveillance", "night",
    "vision", "nvd", "nvg", "drone", "uav", "anti", "radar", "radio",
    "jammer", "laser", "lrf", "binocular", "binoculars", "eoss", "optical",
    "infrared", "security", "armor", "helmet", "ballistic",
}


def _important_search_terms(search: str) -> list[str]:
    return [term for term in _search_terms(search) if term not in SEARCH_GENERIC_TERMS]


def _rank_tender(tender: Tender, q: str) -> int:
    raw = tender.raw_data or {}
    text = " ".join(
        str(part)
        for part in [
            tender.title,
            tender.description,
            tender.portal,
            tender.state,
            raw.get("department"),
            raw.get("buyer"),
            raw.get("tender_number"),
            raw.get("tender_display_id"),
            raw.get("procurement_id"),
            raw.get("reference_no"),
            raw.get("bid_number"),
            raw.get("nit_id"),
        ]
        if part
    ).lower()
    phrase = q.strip().lower()
    terms = _search_terms(q)
    important_terms = _important_search_terms(q)
    domain_terms = [term for term in terms if term in SEARCH_DOMAIN_TERMS]
    matched_terms = [term for term in terms if term in text]
    matched_important = [term for term in important_terms if term in text]
    matched_domain = [term for term in domain_terms if term in text]
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
    try:
        score += min(int(raw.get("match_score") or 0), 30)
    except (TypeError, ValueError):
        pass
    if tender.matched_keywords:
        score += 5
    return score


@router.post("/search-now")
async def scrape_and_search(
    q: str = Query(..., min_length=2),
    limit: int = Query(20, ge=1, le=50),
    _user=Depends(get_current_user),
):
    status = scraper_runtime_status()
    if status["running"]:
        scrape_result = {
            "status": "already_running",
            "portals": status["portal_count"],
            "tenders_found": 0,
            "updated_tenders": 0,
            "message": "Scraper is already running. Returning current archive results while live updates continue.",
        }
    else:
        push_log(f"Keyword search requested live refresh: {q}")
        task = asyncio.create_task(asyncio.to_thread(run_all_scrapers_sync))
        _background_scrape_tasks.add(task)

        def cleanup(done_task: asyncio.Task) -> None:
            _background_scrape_tasks.discard(done_task)
            try:
                result = done_task.result()
                push_log(
                    f"Keyword refresh finished for '{q}': "
                    f"{result.get('tenders_found', 0)} new, {result.get('updated_tenders', 0)} refreshed"
                )
            except Exception as exc:
                push_log(f"Keyword refresh failed for '{q}': {str(exc)[:180]}")

        task.add_done_callback(cleanup)
        scrape_result = {
            "status": "started",
            "portals": status["portal_count"],
            "tenders_found": 0,
            "updated_tenders": 0,
            "message": "Live scrape started in the background. Returning current archive results immediately.",
        }
    db = SessionLocal()
    try:
        terms = _search_terms(q)
        clauses = [Tender.title.ilike(f"%{q}%"), Tender.description.ilike(f"%{q}%")]
        for term in terms:
            clauses.extend([Tender.title.ilike(f"%{term}%"), Tender.description.ilike(f"%{term}%")])
        candidates = db.query(Tender).filter(Tender.is_active.is_(True), or_(*clauses)).order_by(Tender.scraped_at.desc()).limit(5000).all()
        scored = [(tender, _rank_tender(tender, q)) for tender in candidates]
        positive = [(tender, score) for tender, score in scored if score > 0]
        ranked = [tender for tender, _score in sorted(positive or scored, key=lambda item: (item[1], item[0].scraped_at), reverse=True)]
        return {
            "query": q,
            "scrape": scrape_result,
            "count": len(ranked),
            "results": [
                {
                    "id": tender.id,
                    "title": tender.title,
                    "portal": tender.portal,
                    "state": tender.state,
                    "closing_date": tender.closing_date,
                    "opening_date": tender.opening_date,
                    "matched_keywords": tender.matched_keywords or [],
                    "summary": (tender.raw_data or {}).get("plain_summary"),
                    "score": _rank_tender(tender, q),
                }
                for tender in ranked[:limit]
            ],
        }
    finally:
        db.close()


@router.get("/portals", response_model=list[PortalOut])
def list_portals(db: Session = Depends(get_db), _user=Depends(get_current_user)):
    sync_portal_registry(db)
    rows = db.query(ProcurementPortal).order_by(ProcurementPortal.name.asc()).all()
    return [
        {
            "id": row.id,
            "name": row.name,
            "url": row.url,
            "portal_type": row.portal_type,
            "kind": row.portal_type,
            "state": row.state,
            "authentication": row.authentication,
            "scraper_type": row.scraper_type,
            "uses_playwright": row.scraper_type == "playwright",
            "scheduler": row.scheduler,
            "retry_count": row.retry_count,
            "health_status": row.health_status,
            "proxy_configuration": row.proxy_configuration or {},
            "captcha_strategy": row.captcha_strategy,
            "last_successful_run": row.last_successful_run,
            "next_run": row.next_run,
            "enabled": row.enabled,
            "listing_urls": row.listing_urls or [row.url],
        }
        for row in rows
    ]


@router.patch("/portals/{portal_name}", response_model=PortalOut)
def update_portal(portal_name: str, payload: PortalUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    sync_portal_registry(db)
    portal = db.query(ProcurementPortal).filter(ProcurementPortal.name == portal_name).first()
    if not portal:
        raise HTTPException(status_code=404, detail="Portal not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(portal, field, value)
    portal.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(portal)
    return {
        "id": portal.id,
        "name": portal.name,
        "url": portal.url,
        "portal_type": portal.portal_type,
        "kind": portal.portal_type,
        "state": portal.state,
        "authentication": portal.authentication,
        "scraper_type": portal.scraper_type,
        "uses_playwright": portal.scraper_type == "playwright",
        "scheduler": portal.scheduler,
        "retry_count": portal.retry_count,
        "health_status": portal.health_status,
        "proxy_configuration": portal.proxy_configuration or {},
        "captcha_strategy": portal.captcha_strategy,
        "last_successful_run": portal.last_successful_run,
        "next_run": portal.next_run,
        "enabled": portal.enabled,
        "listing_urls": portal.listing_urls or [portal.url],
    }


@router.post("/portals/{portal_name}/run")
async def run_portal(portal_name: str, user: User = Depends(get_current_user)):
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    result = await asyncio.to_thread(run_one_scraper_sync, portal_name)
    if result.get("status") == "not_found":
        raise HTTPException(status_code=404, detail="Portal not found")
    return result


@router.get("/portals/{portal_name}/runs", response_model=list[PortalRunOut])
def portal_runs(portal_name: str, limit: int = Query(20, ge=1, le=100), db: Session = Depends(get_db), _user=Depends(get_current_user)):
    return (
        db.query(PortalRun)
        .filter(PortalRun.portal == portal_name)
        .order_by(PortalRun.started_at.desc())
        .limit(limit)
        .all()
    )


@router.get("/portals/{portal_name}/stats")
def portal_stats(portal_name: str, db: Session = Depends(get_db), _user=Depends(get_current_user)):
    sync_portal_registry(db)
    portal = db.query(ProcurementPortal).filter(ProcurementPortal.name == portal_name).first()
    if not portal:
        raise HTTPException(status_code=404, detail="Portal not found")
    tenders = db.query(Tender).filter(Tender.portal == portal.name, Tender.is_active.is_(True)).all()
    runs = db.query(PortalRun).filter(PortalRun.portal == portal.name).order_by(PortalRun.started_at.desc()).limit(100).all()
    matched = [t for t in tenders if (t.matched_keywords or []) or (t.categories or [])]
    documents = (
        db.query(TenderDocument)
        .join(Tender, TenderDocument.tender_id == Tender.id)
        .filter(Tender.portal == portal.name)
        .all()
    )
    successful_runs = [run for run in runs if run.status in {"success", "empty", "cached"}]
    return {
        "portal": portal.name,
        "status": portal.health_status,
        "enabled": portal.enabled,
        "fetched": sum(run.fetched_count or 0 for run in runs),
        "stored": len(tenders),
        "matched": len(matched),
        "unmatched": max(0, len(tenders) - len(matched)),
        "duplicate": sum(run.duplicate_count or 0 for run in runs),
        "failed": sum(run.failed_count or 0 for run in runs),
        "updated": sum(run.updated_count or 0 for run in runs),
        "last_run": runs[0].started_at if runs else None,
        "next_run": portal.next_run,
        "average_runtime_seconds": round(
            sum((run.finished_at - run.started_at).total_seconds() for run in runs if run.finished_at) / max(1, len([run for run in runs if run.finished_at])),
            2,
        ),
        "success_rate": round((len(successful_runs) / max(1, len(runs))) * 100, 1),
        "retry_count": portal.retry_count,
        "documents": {
            "queued": len([doc for doc in documents if doc.status == "queued"]),
            "processed": len([doc for doc in documents if doc.status == "processed"]),
            "failed": len([doc for doc in documents if doc.status == "failed"]),
        },
    }


@router.get("/stream")
async def scrape_stream(token: str = Query(...)):
    token_payload(token)

    async def event_gen():
        last = max(0, len(_scrape_log) - 50)
        last_heartbeat = datetime.utcnow().timestamp()
        while True:
            while last < len(_scrape_log):
                yield f"data: {json.dumps(_scrape_log[last])}\n\n"
                last += 1
                last_heartbeat = datetime.utcnow().timestamp()
            now = datetime.utcnow().timestamp()
            if now - last_heartbeat >= 15:
                yield ": keepalive\n\n"
                last_heartbeat = now
            await asyncio.sleep(0.5)

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/logs", response_model=list[ScrapeLogOut])
def scrape_logs(limit: int = 50, db: Session = Depends(get_db), _user=Depends(get_current_user)):
    return db.query(ScrapeLog).order_by(ScrapeLog.scraped_at.desc()).limit(min(limit, 200)).all()


@router.get("/documents/status")
def document_queue_status(db: Session = Depends(get_db), _user=Depends(get_current_user)):
    statuses = {}
    for status_name, in db.query(TenderDocument.status).distinct().all():
        statuses[status_name or "unknown"] = db.query(TenderDocument).filter(TenderDocument.status == status_name).count()
    return {
        "total": db.query(TenderDocument).count(),
        "queued": statuses.get("queued", 0),
        "processing": statuses.get("processing", 0),
        "processed": statuses.get("processed", 0),
        "downloaded": statuses.get("downloaded", 0),
        "failed": statuses.get("failed", 0),
        "by_status": statuses,
    }


@router.post("/documents/process")
def process_documents(limit: int = Query(20, ge=1, le=100), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return process_queued_documents(db, limit=limit)


@router.delete("/demo-data", response_model=CleanupOut)
def clear_demo_data(db: Session = Depends(get_db), _user=Depends(get_current_user)):
    deleted = 0
    for tender in db.query(Tender).all():
        source = (tender.raw_data or {}).get("source")
        if source in {"seed", "sample_fallback"} or tender.tender_id.startswith("demo-"):
            db.delete(tender)
            deleted += 1
    db.commit()
    return {"deleted": deleted}
