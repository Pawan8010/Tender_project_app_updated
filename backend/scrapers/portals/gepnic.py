from typing import Any

from ..base_scraper import BaseScraper


class GePNICScraper(BaseScraper):

    async def scrape(self, search_query: str | None = None) -> list[dict[str, Any]]:
        tenders = []
        seen = set()
        for url in self.listing_urls:
            try:
                soup = await self.fetch_static(url)
                parsed = self._parse_candidates(soup, source_url=url, scrape_method="gepnic_static")
                await self._enrich_missing_schedule(parsed)
            except Exception as exc:
                print(f"GePNIC URL failed {url}: {exc}")
                continue
            for tender in parsed:
                if tender["tender_id"] in seen:
                    continue
                seen.add(tender["tender_id"])
                tenders.append(tender)
        return tenders
