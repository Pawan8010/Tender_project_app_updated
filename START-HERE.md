# Apna Tender - Clone And Run Guide

This repository contains the existing Apna Tender platform: FastAPI backend, React dashboard, authentication, real-time tender scraper, Google-assisted discovery fallback, AI search, document processing, and dashboard monitoring.

The repository intentionally does not include local secrets, Gmail passwords, downloaded tender documents, logs, backups, or SQLite runtime databases. Each machine creates its own local database or connects to PostgreSQL through `.env`.

## Requirements

- Python 3.11 or newer
- Node.js 18 or newer
- PostgreSQL for production use, or SQLite for quick local testing
- Chrome/Chromium dependencies installed by Playwright

## 1. Configure Environment

Copy the example environment file:

```powershell
copy .env.example .env
```

Edit `.env` before production use:

```text
ADMIN_EMAIL=your-admin-email@example.com
ADMIN_PASSWORD=replace-with-strong-password
SECRET_KEY=replace-with-long-random-secret
JWT_SECRET=replace-with-long-random-secret
DATABASE_URL=postgresql+psycopg://tenderuser:password@127.0.0.1:5432/tenderdb
```

For Gmail alerts, create a Gmail App Password and set:

```text
GMAIL_USER=yourgmail@gmail.com
GMAIL_APP_PASSWORD=replace-with-gmail-app-password
ALERT_TO_EMAILS=recipient1@example.com,recipient2@example.com
```

For Google Custom Search fallback, enable the Custom Search JSON API in Google Cloud and set:

```text
GOOGLE_SEARCH_API_KEY=your-google-api-key
GOOGLE_SEARCH_CX=your-search-engine-id
```

## 2. Start Backend

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
python -m playwright install chromium
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Backend API docs:

```text
http://127.0.0.1:8000/docs
```

## 3. Start Frontend

Open a second terminal:

```powershell
cd frontend
npm install
npm run dev -- --host 0.0.0.0
```

Open:

```text
http://127.0.0.1:5173
```

If port `5173` is busy, Vite will print the next available local URL.

## 4. One-Command Local Helpers

From the project root:

```powershell
.\run-backend.ps1
.\run-frontend.ps1
```

## 5. Production Build

```powershell
cd frontend
npm install
npm run build
cd ..
```

The Dockerfile builds the frontend automatically and serves the compiled app from the FastAPI backend container.

## 6. Docker

```powershell
copy .env.example .env
docker compose up --build
```

The Docker stack starts PostgreSQL, Redis, backend, worker services, and the frontend/nginx service using the same codebase.

## 7. Real-Time Scraper

The scraper is controlled by environment flags:

```text
AUTO_SCRAPE_ENABLED=true
IN_PROCESS_AUTO_SCRAPE_ENABLED=true
USE_PLAYWRIGHT=true
STORE_ALL_TENDERS=true
ENABLE_SAMPLE_FALLBACK=false
SCRAPER_CONCURRENCY=3
SCRAPER_RETRIES=3
MAX_PAGES_PER_PORTAL=6000
MAX_TENDERS_PER_PORTAL=0
```

Manual controls are available in the dashboard System page and through:

```text
POST /api/scrape/run
GET  /api/scrape/portals
GET  /api/scrape/logs
```

## 8. Before Sharing Publicly

- Never commit `.env`.
- Replace placeholder `SECRET_KEY`, `JWT_SECRET`, and `ADMIN_PASSWORD`.
- Use a Gmail App Password, not the normal Gmail password.
- Keep downloaded tender documents and runtime databases outside Git.
- Check readiness at `http://127.0.0.1:8000/api/health`.
