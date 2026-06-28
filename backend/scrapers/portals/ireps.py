from typing import Any
import asyncio
import random

import httpx
from bs4 import BeautifulSoup
from urllib.parse import urljoin

from ..base_scraper import BaseScraper, USER_AGENTS


class IREPSScraper(BaseScraper):

    async def scrape(self, search_query: str | None = None) -> list[dict[str, Any]]:
        login_url = "https://www.ireps.gov.in/epsn/guestLogin.do"
        cfg = __import__("app.config", fromlist=["settings"]).settings()
        headers = {
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-IN,en;q=0.9",
            "Referer": login_url,
        }
        tenders = []
        seen = set()
        async with httpx.AsyncClient(
            timeout=cfg["scraper_request_timeout_seconds"],
            follow_redirects=True,
            headers=headers,
            verify=False,
        ) as client:
            response = await client.get(login_url)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")
            form = soup.select_one("form")
            if form:
                data = {}
                for field in form.select("input"):
                    name = field.get("name")
                    if name:
                        data[name] = field.get("value", "")
                action = urljoin(str(response.url), form.get("action") or login_url)
                try:
                    await client.post(action, data=data, headers={**headers, "Referer": str(response.url)})
                except Exception as exc:
                    print(f"IREPS guest session POST failed: {exc}")

            candidates = [
                "https://www.ireps.gov.in/epsn/home/viewEOIAdvertised.do",
                "https://www.ireps.gov.in/epsn/home/viewGlobalTender.do",
                login_url,
            ]
            for url in candidates:
                try:
                    page = await client.get(url)
                    page.raise_for_status()
                    parsed = self._parse_candidates(BeautifulSoup(page.text, "html.parser"), source_url=url, scrape_method="ireps_guest_session")
                    await self._enrich_missing_schedule(parsed)
                except Exception as exc:
                    print(f"IREPS listing failed {url}: {exc}")
                    continue
                for tender in parsed:
                    if tender["tender_id"] in seen:
                        continue
                    seen.add(tender["tender_id"])
                    tenders.append(tender)
        return tenders
