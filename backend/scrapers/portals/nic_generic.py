from typing import Any

from ..base_scraper import BaseScraper


class NICGenericScraper(BaseScraper):

    async def scrape(self, search_query: str | None = None) -> list[dict[str, Any]]:
        cfg = __import__("app.config", fromlist=["settings"]).settings()
        tenders = []
        seen = set()
        for nic_url in self.listing_urls:
            parsed_pages = await self.scrape_tapestry_listing_pages(nic_url)
            for tender in parsed_pages:
                if tender["tender_id"] in seen:
                    continue
                seen.add(tender["tender_id"])
                tenders.append(tender)
                if cfg["max_tenders_per_portal"] and len(tenders) >= cfg["max_tenders_per_portal"]:
                    return tenders

            try:
                soup = await self.fetch_static(nic_url)
                parsed = self._parse_candidates(soup, source_url=nic_url, scrape_method="nic_static_fallback")
                await self.enrich_detail_pages(parsed)
                for tender in parsed:
                    if tender["tender_id"] in seen:
                        continue
                    seen.add(tender["tender_id"])
                    tenders.append(tender)
                    if cfg["max_tenders_per_portal"] and len(tenders) >= cfg["max_tenders_per_portal"]:
                        return tenders
            except Exception as exc:
                print(f"{self.portal_name} static fallback failed: {exc}")
        return tenders
