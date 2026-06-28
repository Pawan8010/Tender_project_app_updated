from typing import Any
import asyncio
import json
import re
import random
from datetime import date

import httpx

from ..base_scraper import BaseScraper, USER_AGENTS


class GujaratScraper(BaseScraper):

    async def scrape(self, search_query: str | None = None) -> list[dict[str, Any]]:
        cfg = __import__("app.config", fromlist=["settings"]).settings()
        calendar_url = "https://tender.nprocure.com/dashboard/getTenderClosingData"
        report_url = "https://tender.nprocure.com/beforeLoginBidSubmissionClosingReport"
        calendar_soup = await self.fetch_static(calendar_url)
        calendar_html = str(calendar_soup)
        match = re.search(r"tenderCounts\s*=\s*JSON\.parse\('(?P<data>\{.*?\})'\)", calendar_html, re.DOTALL)
        if not match:
            raise RuntimeError("nProcure closing calendar counts not found")

        try:
            tender_counts = json.loads(match.group("data"))
        except json.JSONDecodeError as exc:
            raise RuntimeError("nProcure closing calendar JSON could not be parsed") from exc

        dated_counts = []
        today = date.today()
        for raw_date_str, count in tender_counts.items():
            parsed_date = self._parse_iso_date(raw_date_str)
            if parsed_date and parsed_date >= today and int(count or 0) > 0:
                dated_counts.append((parsed_date, int(count)))
        if not dated_counts:
            for raw_date_str, count in tender_counts.items():
                parsed_date = self._parse_iso_date(raw_date_str)
                if parsed_date and int(count or 0) > 0:
                    dated_counts.append((parsed_date, int(count)))
        dated_counts.sort(key=lambda item: item[0])

        tenders = []
        seen = set()
        async with httpx.AsyncClient(
            timeout=cfg["scraper_request_timeout_seconds"],
            follow_redirects=True,
            verify=False,
            headers={
                "User-Agent": random.choice(USER_AGENTS),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-IN,en;q=0.9",
                "Referer": calendar_url,
            },
        ) as client:
            for closing_day, _count in dated_counts:
                soup = await self._fetch_nprocure_closing_report(client, report_url, closing_day.isoformat())
                for tender in self._parse_nprocure_closing_report(soup, report_url, calendar_url, closing_day):
                    if tender["tender_id"] in seen:
                        continue
                    seen.add(tender["tender_id"])
                    tenders.append(tender)

        return tenders
