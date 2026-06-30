# Apna Tender

A working FastAPI + React platform for real-time government tender scraping, AI-assisted tender search, alerts, document processing, and dashboard monitoring.

## What Is Included

- FastAPI backend with JWT-style bearer auth and session tracking
- Installed PostgreSQL 18 database support for local and Docker-backed services
- SQLAlchemy models for tenders, users, keywords, alert subscriptions, and scrape logs
- Keyword engine with the supplied defense/surveillance library and category tagging
- 23-portal scraper registry covering 6 national and 17 state portals
- Celery worker and beat scheduler for configured interval-based proposal-aligned scraping
- Gmail SMTP alert integration, test email endpoint, and daily digest support when SMTP credentials are configured
- AI search endpoints with local tender index ranking and optional Google Custom Search discovery fallback
- CSV and Excel export endpoints
- Tender backup vault with automatic matched-tender snapshots, manual full backups, JSON download, and restore for missing/inactive tenders
- React dashboard with 6-card stats, filters, matched-only mode, tender detail rail, alerts, admin keyword management, live scrape status, and manual scrape trigger
- On-premise Docker Compose stack with PostgreSQL, Redis, backend, Celery worker, Celery beat, frontend, and nginx reverse proxy

## Accounts

The backend seeds one admin account for the owner. Set these values in `.env` before first production start:

```text
ADMIN_EMAIL=admin@example.com
ADMIN_PASSWORD=replace-with-strong-admin-password
```

Visitors can create their own standard user account from the Sign up tab on the auth screen.

## Local Development

This project can use PostgreSQL through `.env`, and falls back to a local SQLite database for quick development when `DATABASE_URL` is not set.

```text
DATABASE_URL=postgresql+psycopg://tenderuser:replace-with-postgres-password@127.0.0.1:5432/tenderdb
```

The app database is `tenderdb`, owned by `tenderuser`. Local development can use your installed PostgreSQL server on port `5432`; Docker Compose starts its own PostgreSQL service.

Backend:

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Frontend:

```bash
cd frontend
npm install
npm run dev
```

Open `http://127.0.0.1:5173`. If another local app is already using 5173, `run-frontend.ps1` falls back to `http://127.0.0.1:5174`.

## Temporary Share Link Without Deployment

Keep the backend and frontend running locally, then expose the Vite frontend through a tunnel:

```powershell
cd frontend
npm run build
cd ..
node .\share-server.mjs
npx --yes localtunnel --port 4174 --local-host 127.0.0.1
```

Share the printed `https://...loca.lt` URL. The share server serves the built React app and proxies `/api` to the local FastAPI backend, so sign up, sign in, search, exports, and scrape actions work through the same public URL while your machine and terminal stay online.

On Windows, you can also run these from the project root in two terminals:

```powershell
.\run-backend.ps1
.\run-frontend.ps1
```

## Docker

Copy the example environment and start the full stack:

```bash
copy .env.example .env
docker compose up --build
```

The Docker backend service is named `backend`; no named Compose profile is required. Docker Compose is production-oriented by default: it runs PostgreSQL, Redis, FastAPI, Celery worker, Celery Beat, React/nginx, health checks, and no backend `--reload` mode. The Docker stack uses the `postgres` service internally, while local development can still use your installed PostgreSQL server through `DATABASE_URL`.

For one-command on-prem deployment from a Linux server:

```bash
chmod +x deploy.sh
./deploy.sh
```

## Real-Time Scraping

Local FastAPI runs an automatic background scrape loop by default:

```text
AUTO_SCRAPE_ENABLED=true
IN_PROCESS_AUTO_SCRAPE_ENABLED=true
AUTO_SCRAPE_INTERVAL_MINUTES=60
AUTO_SCRAPE_STARTUP_DELAY_SECONDS=15
SEED_DEMO_DATA=false
ENABLE_SAMPLE_FALLBACK=false
STORE_ALL_TENDERS=true
ALERT_TO_EMAILS=alerts@example.com
ADMIN_EMAIL=admin@example.com
ADMIN_PASSWORD=replace-with-strong-admin-password
USE_PLAYWRIGHT=true
SCRAPER_REQUEST_TIMEOUT_SECONDS=15
SCRAPER_PORTAL_TIMEOUT_SECONDS=60
SCRAPER_RETRIES=3
SCRAPER_CONCURRENCY=6
BACKUP_ENABLED=true
BACKUP_DIR=backups
BACKUP_RETENTION_COUNT=30
```

This gives you real portal attempts every hour instead of fake demo tenders, matching the uploaded proposal. `STORE_ALL_TENDERS=true` stores every tender-like live record and adds defense/security categories only when keywords match. When a new matched tender is created, the system automatically emails `ALERT_TO_EMAILS` plus any matching in-app alert subscriptions. Existing tenders are refreshed with the latest live portal details while preserving their first-seen timestamp. The dashboard polls tenders and scrape logs every 15 seconds, so new records, refreshed records, cached portal data, and retrying portal states appear automatically.

To route static scraper requests through ScraperAPI, set these in your local `.env`:

```text
USE_PROXY=true
SCRAPER_API_KEY=your_scraperapi_key
```

The project URL-encodes portal URLs before sending them to ScraperAPI so NIC/GEP portals with query-string listing pages are handled correctly. The scraper automation runs on the configured interval, and the React dashboard refreshes tenders, scrape logs, health, backups, and matches every 15 to 30 seconds so new records appear without a page reload.

In Docker, `AUTO_SCRAPE_ENABLED=true` stays enabled for the dashboard and scheduler, while Compose sets `IN_PROCESS_AUTO_SCRAPE_ENABLED=false` for the API container. Celery Beat then schedules the real scraper through Redis, which is the production mode and avoids duplicate scrape loops.

## Backup And Recovery

The platform creates a matched-tender JSON backup after successful scraper cycles when `BACKUP_ENABLED=true`. Operators can also create backups from the System page:

- `Back up matched tenders` protects only keyword-qualified tenders.
- `Back up all tenders` protects the complete active tender store.
- `Download` saves the JSON snapshot for off-machine storage.
- `Restore` brings back missing or inactive tenders without overwriting active live rows.

Backup files are stored under `BACKUP_DIR` and indexed in the `tender_backups` table. `BACKUP_RETENTION_COUNT` keeps the newest snapshots per backup type.

## Scraping Notes

The scraper registry is in `backend/scrapers/registry.py`. Government procurement sites often use captchas, session flows, bot detection, or JavaScript rendering. For that reason the scrapers include retry logic, Playwright support, optional ScraperAPI proxy support, and an optional sample fallback controlled by:

```text
ENABLE_SAMPLE_FALLBACK=false
```

Keep this off for real production scraping. Turn it on only for demos where the network is unavailable. `USE_PLAYWRIGHT=true` enables the browser-rendered scraper for JavaScript-heavy portals; static HTML scraping still runs first for speed.

### Live Scraper Coverage

The current build uses source-specific live paths where they are more accurate than generic HTML:

- GeM: live bid JSON API with proposal keyword search terms and direct bid document links.
- NIC/GEP state portals and CPPP: official `FrontEndListTendersbyDate` form submit flow, which captures published, closing, and opening dates from the original rows.
- Karnataka KPPP: public JSON tender search plus full-view enrichment for department, location, closing date, and opening date where published.
- Andhra Pradesh and Telangana: public homepage tender cards with official tender IDs, IFB numbers, descriptions, and closing dates.
- Bihar: JavaScript-rendered public listing through Playwright.
- GePNIC and IREPS: monitored as reachable public pages; they stay `empty` until the public page exposes parseable tender rows.
- nProcure: official `https://tender.nprocure.com` closing-calendar and bid-submission closing report flow, storing Tender ID, IFB/Tender Notice Number, department, closing date/time, and source metadata. The public report does not expose opening dates, so opening remains blank rather than fabricated.

Each scrape stores `raw_data.scrape_method` so the dashboard and exports can distinguish `gem_json_api`, `kppp_json_api`, `tapestry_form_LinkSubmit_1`, `andhra_public_cards`, `telangana_public_cards`, `dynamic_browser`, and generic static rows.

## API Highlights

- `POST /api/auth/login`
- `GET /api/tenders/`
- `GET /api/tenders/stats`
- `GET /api/tenders/{id}`
- `GET /api/keywords/`
- `POST /api/keywords/`
- `PATCH /api/keywords/{id}`
- `DELETE /api/keywords/{id}`
- `GET /api/alerts/`
- `POST /api/alerts/`
- `POST /api/alerts/test`
- `GET /api/export/csv`
- `GET /api/export/excel`
- `GET /api/health/connections`
- `GET /api/backups/`
- `POST /api/backups/create`
- `GET /api/backups/{id}/download`
- `POST /api/backups/{id}/restore`
- `POST /api/scrape/run`
- `GET /api/scrape/portals`
- `GET /api/scrape/logs`
- `DELETE /api/scrape/demo-data`

API docs are available at `http://127.0.0.1:8000/docs`.

CSV and Excel exports use the same filters as the live tender table: search, category, portal, state, published range, opening range, closing range, quick closing, and matched-only mode. The exported columns follow the procurement-style layout: `SL No.`, `Tender/RFQ ID`, `Tender Description`, `Reference No.`, `Department`, `Opening Date`, `Closing Date`, `Time left`, `Portal`, `State`, `Matched Keywords`, and source `URL`.

## Production Readiness Checklist

- Change `SECRET_KEY`, `JWT_SECRET`, `ADMIN_PASSWORD`, `POSTGRES_PASSWORD`, and `REDIS_PASSWORD` before sharing publicly.
- Keep `.env` outside source control and outside zip/share packages.
- Verify `ALERT_FROM_EMAIL` in SendGrid before relying on alerts.
- Keep `ENABLE_SAMPLE_FALLBACK=false` for real results.
- Use `USE_PROXY=true` with `SCRAPER_API_KEY` when government portals block local traffic.
- Keep `BACKUP_ENABLED=true`, store `BACKUP_DIR` on a durable disk, and periodically copy JSON backups off-machine.
- Run `docker compose up --build -d` for the full service stack, then check `docker compose ps`.
- Confirm readiness at `/api/health/readiness`, detailed dependency status at `/api/health/detailed`, then use the dashboard System page for portal-level status.
