from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text

from app.auth import get_current_user
from app.config import settings
from app.database import SessionLocal
from app.models import PortalRun, ProcurementPortal, ScrapeLog, Tender, TenderBackup, TenderDocument, UserSession
from scrapers.registry import portal_browser_enabled, scraper_runtime_status, sync_portal_registry

router = APIRouter()


def _is_placeholder(value: str | None) -> bool:
    lowered = (value or "").strip().lower()
    return not lowered or lowered.startswith("change-this") or lowered.startswith("changeme") or "replace-with" in lowered


def _safe_url_parts(raw_url: str | None) -> dict:
    parsed = urlparse(raw_url or "")
    return {
        "scheme": parsed.scheme or None,
        "host": parsed.hostname or None,
        "port": parsed.port,
        "database": parsed.path.lstrip("/") or None,
        "username_configured": bool(parsed.username),
        "password_configured": bool(parsed.password),
    }


def _csv_values(value: str | None) -> list[str]:
    return [item.strip() for item in (value or "").split(",") if item.strip()]


def _playwright_available() -> tuple[bool, str | None]:
    try:
        import playwright  # noqa: F401

        return True, None
    except Exception as exc:
        return False, str(exc)


@router.get("")
def health():
    db = SessionLocal()
    tender_count = 0
    latest_scrape = None
    backup_count = 0
    latest_backup = None
    dynamic_portal_count = 0
    session_counts = {"active": 0, "revoked": 0, "expired": 0}
    document_counts = {"queued": 0, "processing": 0, "processed": 0, "downloaded": 0, "failed": 0}
    try:
        tender_count = db.query(Tender).filter(Tender.is_active.is_(True)).count()
        latest = db.query(ScrapeLog).order_by(ScrapeLog.scraped_at.desc()).first()
        latest_scrape = latest.scraped_at if latest else None
        dynamic_portal_count = sum(
            1
            for portal in db.query(ProcurementPortal).filter(ProcurementPortal.enabled.is_(True)).all()
            if portal_browser_enabled(portal)
        )
        backup_count = db.query(TenderBackup).count()
        latest_backup_row = db.query(TenderBackup).order_by(TenderBackup.created_at.desc()).first()
        latest_backup = {
            "id": latest_backup_row.id,
            "file_name": latest_backup_row.file_name,
            "backup_type": latest_backup_row.backup_type,
            "tender_count": latest_backup_row.tender_count,
            "matched_count": latest_backup_row.matched_count,
            "created_at": latest_backup_row.created_at,
        } if latest_backup_row else None
        now = datetime.utcnow()
        session_counts = {
            "active": db.query(UserSession).filter(UserSession.is_active.is_(True), UserSession.revoked.is_(False), UserSession.session_expires_at >= now).count(),
            "revoked": db.query(UserSession).filter(UserSession.revoked.is_(True)).count(),
            "expired": db.query(UserSession).filter(UserSession.refresh_expires_at < now).count(),
        }
        document_counts = {
            "queued": db.query(TenderDocument).filter(TenderDocument.status == "queued").count(),
            "processing": db.query(TenderDocument).filter(TenderDocument.status == "processing").count(),
            "processed": db.query(TenderDocument).filter(TenderDocument.status == "processed").count(),
            "downloaded": db.query(TenderDocument).filter(TenderDocument.status == "downloaded").count(),
            "failed": db.query(TenderDocument).filter(TenderDocument.status == "failed").count(),
        }
    finally:
        db.close()
    cfg = settings()
    now = datetime.utcnow()
    runtime = scraper_runtime_status()
    playwright_available, _playwright_error = _playwright_available()
    browser_enabled = bool(cfg["use_playwright"] or cfg["scraper_force_playwright"]) and playwright_available
    latest_reference = runtime.get("last_finished") or latest_scrape
    latest_scrape_age_seconds = int((now - latest_scrape).total_seconds()) if latest_scrape else None
    next_scrape_at = None
    next_scrape_in_seconds = None
    if cfg["auto_scrape_enabled"] and latest_reference and not runtime.get("running"):
        next_scrape_at = latest_reference + timedelta(minutes=cfg["auto_scrape_interval_minutes"])
        next_scrape_in_seconds = max(0, int((next_scrape_at - now).total_seconds()))

    return {
        "status": "ok",
        "service": "Apna Tender API",
        "version": "2.0.0",
        "server_time": now,
        "auto_scrape_enabled": cfg["auto_scrape_enabled"],
        "auto_scrape_interval_minutes": cfg["auto_scrape_interval_minutes"],
        "scheduler": {
            "enabled": cfg["auto_scrape_enabled"],
            "mode": "fastapi_background_loop" if cfg["in_process_auto_scrape_enabled"] else "celery_beat",
        },
        "tender_count": tender_count,
        "latest_scrape": latest_scrape,
        "latest_scrape_age_seconds": latest_scrape_age_seconds,
        "next_scrape_at": next_scrape_at,
        "next_scrape_in_seconds": next_scrape_in_seconds,
        "scraper": runtime,
        "backup": {
            "enabled": cfg["backup_enabled"],
            "retention_count": cfg["backup_retention_count"],
            "backup_count": backup_count,
            "latest": latest_backup,
            "last_error": runtime.get("last_backup_error"),
        },
        "sessions": session_counts,
        "documents": document_counts,
        "scrape_methods": {
            "static_html": True,
            "dynamic_browser": browser_enabled,
            "playwright_available": playwright_available,
            "api_proxy": bool(cfg["use_proxy"] and cfg["scraper_api_key"]),
            "api_proxy_fallback": bool(cfg["scraper_proxy_fallback"] and cfg["scraper_api_key"]),
            "dynamic_portals": dynamic_portal_count,
        },
    }


@router.get("/detailed")
def detailed_health():
    db = SessionLocal()
    postgres = "ok"
    latest_scrape = None
    try:
        db.execute(text("select 1"))
        latest = db.query(ScrapeLog).order_by(ScrapeLog.scraped_at.desc()).first()
        latest_scrape = latest.scraped_at if latest else None
    except Exception as exc:
        postgres = f"failed: {exc}"
    finally:
        db.close()

    redis = "not_configured_for_local_check"
    try:
        import redis as redis_lib

        client = redis_lib.from_url(settings()["redis_url"], socket_connect_timeout=2)
        redis = "ok" if client.ping() else "failed"
    except Exception as exc:
        redis = f"failed: {exc}"

    return {
        "status": "ok" if postgres == "ok" else "degraded",
        "postgres": postgres,
        "redis": redis,
        "latest_scrape": latest_scrape,
        "scraper": scraper_runtime_status(),
        "checked_at": datetime.utcnow(),
    }


@router.get("/readiness")
def readiness():
    cfg = settings()
    checks = {}
    errors = []

    db = SessionLocal()
    try:
        db.execute(text("select 1"))
        checks["database"] = "ok"
    except Exception as exc:
        checks["database"] = "failed"
        errors.append(f"database: {exc}")
    finally:
        db.close()

    if cfg["auto_scrape_enabled"] and not cfg["in_process_auto_scrape_enabled"]:
        try:
            import redis as redis_lib

            client = redis_lib.from_url(cfg["redis_url"], socket_connect_timeout=2, socket_timeout=2)
            checks["redis"] = "ok" if client.ping() else "failed"
            if checks["redis"] != "ok":
                errors.append("redis: ping failed")
        except Exception as exc:
            checks["redis"] = "failed"
            errors.append(f"redis: {exc}")
    else:
        checks["redis"] = "optional"

    if cfg["backup_enabled"]:
        try:
            Path(cfg["backup_dir"]).mkdir(parents=True, exist_ok=True)
            checks["backup_dir"] = "ok"
        except Exception as exc:
            checks["backup_dir"] = "failed"
            errors.append(f"backup_dir: {exc}")
    else:
        checks["backup_dir"] = "disabled"

    checks["scheduler"] = "enabled" if cfg["auto_scrape_enabled"] else "disabled"
    checks["scraper_runtime"] = scraper_runtime_status()

    if errors:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"status": "not_ready", "checks": checks, "errors": errors, "checked_at": datetime.utcnow().isoformat()},
        )

    return {"status": "ready", "checks": checks, "checked_at": datetime.utcnow()}


@router.get("/connections")
def connection_health(_user=Depends(get_current_user)):
    cfg = settings()
    runtime = scraper_runtime_status()
    warnings = []
    playwright_available, playwright_error = _playwright_available()
    browser_enabled = bool(cfg["use_playwright"] or cfg["scraper_force_playwright"]) and playwright_available

    postgres_status = "ok"
    tender_count = 0
    scrape_log_count = 0
    active_sessions = 0
    revoked_sessions = 0
    dynamic_portal_count = 0
    try:
        db = SessionLocal()
        db.execute(text("select 1"))
        sync_portal_registry(db)
        tender_count = db.query(Tender).filter(Tender.is_active.is_(True)).count()
        scrape_log_count = db.query(ScrapeLog).count()
        active_sessions = db.query(UserSession).filter(UserSession.is_active.is_(True), UserSession.revoked.is_(False)).count()
        revoked_sessions = db.query(UserSession).filter(UserSession.revoked.is_(True)).count()
        dynamic_portal_count = sum(
            1
            for portal in db.query(ProcurementPortal).filter(ProcurementPortal.enabled.is_(True)).all()
            if portal_browser_enabled(portal)
        )
    except Exception as exc:
        postgres_status = f"failed: {exc}"
        warnings.append("PostgreSQL connection failed")
    finally:
        try:
            db.close()
        except Exception:
            pass

    redis_status = "not_checked"
    try:
        import redis as redis_lib

        client = redis_lib.from_url(cfg["redis_url"], socket_connect_timeout=2, socket_timeout=2)
        redis_status = "ok" if client.ping() else "failed"
    except Exception as exc:
        if cfg["in_process_auto_scrape_enabled"]:
            redis_status = "optional_offline"
            warnings.append("Redis is offline in local mode; Docker production starts Redis for Celery scheduling")
        else:
            redis_status = f"failed: {exc}"
            warnings.append("Redis is not reachable; Docker Celery scheduling will need Redis online")

    smtp_configured = bool(cfg.get("gmail_user") and cfg.get("gmail_app_password"))
    if not smtp_configured:
        warnings.append("SMTP/Gmail is not configured; email alerts will not send")

    proxy_enabled = bool(cfg["use_proxy"])
    proxy_fallback_enabled = bool(cfg["scraper_proxy_fallback"])
    scraper_api_configured = not _is_placeholder(cfg["scraper_api_key"])
    if proxy_enabled and not scraper_api_configured:
        warnings.append("ScraperAPI proxy is enabled but no API key is configured")
    if bool(cfg["use_playwright"] or cfg["scraper_force_playwright"]) and not playwright_available:
        warnings.append(f"Playwright is enabled but not importable: {playwright_error}")

    secret_needs_rotation = _is_placeholder(cfg["secret_key"])
    admin_password_needs_rotation = _is_placeholder(cfg["admin_password"])
    if secret_needs_rotation:
        warnings.append("JWT secret is still using a placeholder value")
    if admin_password_needs_rotation:
        warnings.append("Admin password is still using a placeholder value")

    return {
        "status": "ok" if postgres_status == "ok" and not secret_needs_rotation and not admin_password_needs_rotation and (redis_status in {"ok", "optional_offline"}) else "attention",
        "checked_at": datetime.utcnow(),
        "environment": cfg["environment"],
        "database": {
            "status": postgres_status,
            "url": _safe_url_parts(cfg["database_url"]),
            "active_tenders": tender_count,
            "scrape_logs": scrape_log_count,
        },
        "redis": {
            "status": redis_status,
            "url": _safe_url_parts(cfg["redis_url"]),
        },
        "scraper": {
            "auto_scrape_enabled": cfg["auto_scrape_enabled"],
            "in_process_scheduler": cfg["in_process_auto_scrape_enabled"],
            "interval_minutes": cfg["auto_scrape_interval_minutes"],
            "startup_delay_seconds": cfg["auto_scrape_startup_delay_seconds"],
            "request_timeout_seconds": cfg["scraper_request_timeout_seconds"],
            "portal_timeout_seconds": cfg["scraper_portal_timeout_seconds"],
            "retries": cfg["scraper_retries"],
            "concurrency": cfg["scraper_concurrency"],
            "use_playwright": browser_enabled,
            "force_playwright": cfg["scraper_force_playwright"],
            "playwright_available": playwright_available,
            "dynamic_portals": dynamic_portal_count,
            "browser_pool_size": cfg["browser_pool_size"],
            "headless_mode": cfg["headless_mode"],
            "max_pages_per_portal": cfg["max_pages_per_portal"],
            "max_tenders_per_portal": cfg["max_tenders_per_portal"],
            "store_all_tenders": cfg["store_all_tenders"],
            "sample_fallback_enabled": cfg["enable_sample_fallback"],
            "runtime": runtime,
        },
        "proxy": {
            "enabled": proxy_enabled,
            "fallback_enabled": proxy_fallback_enabled,
            "scraper_api_key_configured": scraper_api_configured,
            "proxy_list_count": len(_csv_values(cfg.get("scraper_proxy_list", ""))),
            "status": (
                "active"
                if proxy_enabled and scraper_api_configured
                else "fallback_ready"
                if proxy_fallback_enabled and scraper_api_configured
                else "disabled"
                if not proxy_enabled
                else "needs_key"
            ),
        },
        "email": {
            "smtp_configured": smtp_configured,
            "gmail_user_configured": bool(cfg.get("gmail_user")),
            "from_email": cfg["alert_from_email"],
            "recipient_count": len(_csv_values(cfg["alert_to_emails"])),
            "test_recipient_configured": bool(cfg["alert_test_to_email"]),
            "status": "ready" if smtp_configured and cfg["alert_from_email"] and cfg["alert_to_emails"] else "needs_configuration",
        },
        "ai": {
            "enabled": cfg["ml_engine_enabled"],
            "model": cfg["ml_model_name"],
            "semantic_threshold": cfg["ml_similarity_threshold"],
            "status": "enabled" if cfg["ml_engine_enabled"] else "disabled",
        },
        "auth": {
            "admin_user_configured": bool(cfg["admin_email"]),
            "access_token_expire_minutes": cfg["access_token_expire_minutes"],
            "secret_needs_rotation": secret_needs_rotation,
            "admin_password_needs_rotation": admin_password_needs_rotation,
            "status": "ready" if not secret_needs_rotation and not admin_password_needs_rotation else "rotate_before_deploy",
        },
        "sessions": {
            "active": active_sessions,
            "revoked": revoked_sessions,
            "timeout_minutes": cfg["session_inactivity_minutes"],
            "refresh_days": cfg["refresh_token_expire_days"],
            "remember_me_days": cfg["remember_me_expire_days"],
        },
        "backup": {
            "enabled": cfg["backup_enabled"],
            "directory": cfg["backup_dir"],
            "retention_count": cfg["backup_retention_count"],
            "last_error": runtime.get("last_backup_error"),
        },
        "frontend": {
            "allowed_origins": cfg["frontend_origins"],
            "origin_count": len(cfg["frontend_origins"]),
        },
        "warnings": warnings,
    }


@router.get("/portals")
def portal_health():
    db = SessionLocal()
    try:
        sync_portal_registry(db)
        rows = []
        for portal in db.query(ProcurementPortal).order_by(ProcurementPortal.name.asc()).all():
            latest = db.query(ScrapeLog).filter(ScrapeLog.portal == portal.name).order_by(ScrapeLog.scraped_at.desc()).first()
            latest_run = db.query(PortalRun).filter(PortalRun.portal == portal.name).order_by(PortalRun.started_at.desc()).first()
            tender_count = db.query(Tender).filter(Tender.portal == portal.name, Tender.is_active.is_(True)).count()
            document_queue = (
                db.query(TenderDocument)
                .join(Tender, TenderDocument.tender_id == Tender.id)
                .filter(Tender.portal == portal.name, TenderDocument.status.in_(["queued", "processing"]))
                .count()
            )
            latest_status = latest.status if latest else None
            status_value = portal.health_status or latest_status or "never_scraped"
            if latest_status in {"success", "empty", "cached"}:
                status_value = latest_status
            elif tender_count and latest_status in {"failed", "retrying", "temporarily_blocked"}:
                status_value = "cached"
            elif not latest and portal.enabled:
                status_value = "monitored"
            rows.append(
                {
                    "portal": portal.name,
                    "state": portal.state,
                    "status": status_value,
                    "enabled": portal.enabled,
                    "uses_playwright": portal_browser_enabled(portal),
                    "scraper_type": portal.scraper_type,
                    "tenders_found": latest.tenders_found if latest else 0,
                    "stored": tender_count,
                    "duplicates": latest_run.duplicate_count if latest_run else 0,
                    "document_queue": document_queue,
                    "scraped_at": latest.scraped_at if latest else None,
                    "next_run": portal.next_run,
                    "error_message": latest.error_message if latest else None,
                }
            )
        return rows
    finally:
        db.close()
