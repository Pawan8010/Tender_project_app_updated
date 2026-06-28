from typing import Any
import asyncio
import random

import httpx
from bs4 import BeautifulSoup

from ..base_scraper import BaseScraper, USER_AGENTS


class BiharScraper(BaseScraper):

    async def scrape(self, search_query: str | None = None) -> list[dict[str, Any]]:
        cfg = __import__("app.config", fromlist=["settings"]).settings()
        url = self.listing_urls[0]
        payloads = [
            {"tenderStatus": "O", "tenderType": "", "department": "", "searchText": ""},
            {"tenderStatus": "Open", "tenderType": "", "department": "", "searchText": ""},
        ]
        headers = {
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-IN,en;q=0.9",
            "Referer": url,
            "Content-Type": "application/x-www-form-urlencoded",
        }
        tenders = []
        seen = set()
        async with httpx.AsyncClient(
            timeout=cfg["scraper_request_timeout_seconds"],
            follow_redirects=True,
            headers=headers,
            verify=False,
        ) as client:
            await client.get(url)
            for payload in payloads:
                try:
                    response = await client.post(url, data=payload)
                    response.raise_for_status()
                    soup = BeautifulSoup(response.text, "html.parser")
                    parsed = self._parse_candidates(soup, source_url=url, scrape_method="bihar_open_tender_post")
                    await self._enrich_missing_schedule(parsed)
                except Exception as exc:
                    print(f"Bihar POST failed: {exc}")
                    continue
                for tender in parsed:
                    if tender["tender_id"] in seen:
                        continue
                    seen.add(tender["tender_id"])
                    tenders.append(tender)
                if tenders:
                    break
        return tenders
