import asyncio
from contextlib import suppress

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import os

from app.config import settings
from app.database import SessionLocal, init_db
from app.auth import cleanup_expired_sessions
from app.routers import alerts, auth, backups, export, health as health_router, help as help_router, keywords, ml_search, scrape, tenders, users
from app.services.document_processor import process_queued_documents
from app.seed import seed_defaults
from scrapers.registry import run_all_scrapers_sync, sync_portal_registry

app = FastAPI(title="Government Tender Intelligence Platform", version="1.0.0")
auto_scrape_task: asyncio.Task | None = None
session_cleanup_task: asyncio.Task | None = None
document_processor_task: asyncio.Task | None = None

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings()["frontend_origins"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)
app.add_middleware(GZipMiddleware, minimum_size=1000)


@app.middleware("http")
async def production_headers(request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    response.headers.setdefault("Cache-Control", "no-store" if request.url.path.startswith("/api/") else "public, max-age=300")
    return response

app.include_router(auth.router, prefix="/api/auth", tags=["Auth"])
app.include_router(tenders.router, prefix="/api/tenders", tags=["Tenders"])
app.include_router(alerts.router, prefix="/api/alerts", tags=["Alerts"])
app.include_router(backups.router, prefix="/api/backups", tags=["Backups"])
app.include_router(export.router, prefix="/api/export", tags=["Export"])
app.include_router(keywords.router, prefix="/api/keywords", tags=["Keywords"])
app.include_router(scrape.router, prefix="/api/scrape", tags=["Scraping"])
app.include_router(users.router, prefix="/api/users", tags=["Users"])
app.include_router(health_router.router, prefix="/api/health", tags=["Health"])
app.include_router(help_router.router, prefix="/api/help", tags=["Help"])
app.include_router(ml_search.router, prefix="/api/ml", tags=["ML Search"])

from fastapi.responses import FileResponse, HTMLResponse
import os

static_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static")
if os.path.exists(static_dir):
    app.mount("/assets", StaticFiles(directory=os.path.join(static_dir, "assets")), name="assets")

@app.get("/{full_path:path}")
async def serve_frontend(full_path: str):
    if full_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="Not Found")
        
    if os.path.exists(static_dir):
        path = os.path.join(static_dir, full_path)
        if os.path.isfile(path):
            return FileResponse(path)
        return FileResponse(os.path.join(static_dir, "index.html"))
    else:
        # Frontend not built or wrong Dockerfile used
        if full_path == "" or full_path == "/":
            html_content = """
            <html>
                <head><title>Setup Incomplete</title></head>
                <body style="font-family: sans-serif; padding: 2rem;">
                    <h2>API is running, but Frontend is missing</h2>
                    <p>It looks like Render built this using the <code>backend/Dockerfile</code> instead of the new root <code>Dockerfile</code>.</p>
                    <p>To fix this, please go to your Render Dashboard:</p>
                    <ol>
                        <li>Open your Web Service settings.</li>
                        <li>Set <strong>Root Directory</strong> to empty or <code>.</code> (if it is set to backend).</li>
                        <li>Set <strong>Docker Build Context</strong> to <code>.</code></li>
                        <li>Set <strong>Dockerfile Path</strong> to <code>./Dockerfile</code> (or just <code>Dockerfile</code>).</li>
                        <li>Save Changes and click <strong>Manual Deploy &gt; Deploy latest commit</strong>.</li>
                    </ol>
                    <p>Once you do this, Render will build both the frontend and backend together.</p>
                </body>
            </html>
            """
            return HTMLResponse(content=html_content, status_code=200)
        raise HTTPException(status_code=404, detail="Not Found")


async def _auto_scrape_loop():
    cfg = settings()
    await asyncio.sleep(cfg["auto_scrape_startup_delay_seconds"])
    while True:
        try:
            await asyncio.to_thread(run_all_scrapers_sync)
        except Exception as exc:
            print(f"Auto scrape failed: {exc}")
        await asyncio.sleep(cfg["auto_scrape_interval_minutes"] * 60)


async def _session_cleanup_loop():
    cfg = settings()
    await asyncio.sleep(10)
    while True:
        db = SessionLocal()
        try:
            expired = cleanup_expired_sessions(db)
            if expired:
                db.commit()
        except Exception as exc:
            db.rollback()
            print(f"Session cleanup failed: {exc}")
        finally:
            db.close()
        await asyncio.sleep(cfg["session_cleanup_interval_minutes"] * 60)


async def _document_processor_loop():
    await asyncio.sleep(20)
    while True:
        db = SessionLocal()
        try:
            result = process_queued_documents(db, limit=10)
            if result["processed"] or result["failed"]:
                try:
                    from app.routers.scrape import push_log

                    push_log(f"Document processor: {result['processed']} processed, {result['failed']} failed")
                except Exception:
                    pass
        except Exception as exc:
            db.rollback()
            print(f"Document processor failed: {exc}")
        finally:
            db.close()
        await asyncio.sleep(60)


@app.on_event("startup")
async def startup():
    global auto_scrape_task, session_cleanup_task, document_processor_task
    init_db()
    db = SessionLocal()
    try:
        seed_defaults(db)
        sync_portal_registry(db)
    finally:
        db.close()
    cfg = settings()
    session_cleanup_task = asyncio.create_task(_session_cleanup_loop())
    document_processor_task = asyncio.create_task(_document_processor_loop())
    if cfg["auto_scrape_enabled"] and cfg["in_process_auto_scrape_enabled"]:
        auto_scrape_task = asyncio.create_task(_auto_scrape_loop())


@app.on_event("shutdown")
async def shutdown():
    if auto_scrape_task:
        auto_scrape_task.cancel()
        with suppress(asyncio.CancelledError):
            await auto_scrape_task
    if session_cleanup_task:
        session_cleanup_task.cancel()
        with suppress(asyncio.CancelledError):
            await session_cleanup_task
    if document_processor_task:
        document_processor_task.cancel()
        with suppress(asyncio.CancelledError):
            await document_processor_task
