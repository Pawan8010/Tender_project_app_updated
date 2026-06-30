import asyncio
from typing import Any
from ..base_scraper import BaseScraper
from app.config import settings

class KarnatakaScraper(BaseScraper):
    def __init__(self, portal_name="Karnataka eProcurement", base_url="", state="Karnataka", **kwargs):
        super().__init__(portal_name=portal_name, base_url=base_url, state=state, **kwargs)

    async def scrape(self, search_query: str | None = None) -> list[dict[str, Any]]:
        tenders = []
        seen = set()
        cfg = settings()
        
        for url in self.listing_urls:
            page = 1
            while page <= cfg.get("max_pages_per_portal", 5):
                try:
                    # Append pagination parameter if beyond page 1
                    target_url = f"{url}?page={page}" if page > 1 else url
                    soup = await self.soup(target_url)
                    
                    parsed = self._parse_candidates(
                        soup, 
                        source_url=target_url, 
                        scrape_method=f"playwright_karnataka_page_{page}"
                    )
                    
                    if not parsed:
                        break # Stop if no tenders found on this page
                        
                    await self._enrich_missing_schedule(parsed)
                    
                    new_on_page = 0
                    for tender in parsed:
                        if tender["tender_id"] in seen:
                            continue
                            
                        seen.add(tender["tender_id"])
                        new_on_page += 1
                        tenders.append(tender)
                        
                        if cfg.get("max_tenders_per_portal") and len(tenders) >= cfg["max_tenders_per_portal"]:
                            return tenders
                            
                    if new_on_page == 0:
                        break # Stop if we are just seeing duplicates
                        
                    page += 1
                    await asyncio.sleep(1)
                    
                except Exception as exc:
                    print(f"{self.portal_name} page {page} failed: {exc}")
                    break
                    
        return tenders
