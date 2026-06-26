# Tender Hunting System - Working Package

This package includes the backend, frontend, scraper code, current SQLite tender archive, and backup snapshots.

## Quick Start

1. Start the backend:

   ```powershell
   .\run-backend.ps1
   ```

2. In a second PowerShell window, start the frontend:

   ```powershell
   .\run-frontend.ps1
   ```

3. Open the app:

   ```text
   http://127.0.0.1:5173
   ```

4. Login:

   ```text
   2317056@ritindia.edu
   8010
   ```

## Included Data

- The local database is `backend/data/tender_hunter.db`.
- Matched tender backups are in `backend/backups`.
- The scraper is enabled and runs automatically every 60 minutes.
- Manual scraper controls are available inside the System page.

## Production Notes

- For PostgreSQL, change `DATABASE_URL` in `backend/.env`.
- For Gmail alerts, set `GMAIL_USER` and `GMAIL_APP_PASSWORD` in `backend/.env`.
- For proxy scraping, set `USE_PROXY=true` and add `SCRAPER_API_KEY`.
- The base install uses reliable fuzzy matching. Install `backend/requirements-ml.txt` only if you want local sentence-transformer semantic matching.
