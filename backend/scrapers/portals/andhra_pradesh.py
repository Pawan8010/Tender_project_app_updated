from typing import Any
import re

from ..base_scraper import BaseScraper


class AndhraScraper(BaseScraper):

    async def scrape(self, search_query: str | None = None) -> list[dict[str, Any]]:
        url = "https://tender.apeprocurement.gov.in/login.html"
        soup = await self.fetch_static(url)
        tenders = []
        seen = set()
        for block in soup.select(".samer"):
            text = self.clean_text(block.get_text(" "))
            tender_anchor = block.select_one(".coli-id")
            number_anchor = block.select_one(".coli-tno")
            desc_anchor = block.select_one(".tDesc")
            closing_text = self.clean_text(block.select_one(".coli-date").get_text(" ") if block.select_one(".coli-date") else "")
            procurement_match = re.search(r"viewtender\((\d+)\)", str(block), re.IGNORECASE)
            procurement_id = procurement_match.group(1) if procurement_match else None
            display_id = self.clean_text(tender_anchor.get_text(" ") if tender_anchor else "")
            ifb_number = self.clean_text(number_anchor.get_text(" ") if number_anchor else "")
            description = self.clean_text(desc_anchor.get_text(" ") if desc_anchor else text)
            title_text = tender_anchor.get("title") if tender_anchor and tender_anchor.has_attr("title") else ""
            title_text = self.clean_text(title_text.strip("()") or ifb_number or description)
            if not display_id or not title_text:
                continue
            tender_number = ifb_number or display_id
            title = f"{display_id} - {title_text}"
            tender_id = self.generate_tender_id(display_id, procurement_id or tender_number)
            if tender_id in seen:
                continue
            seen.add(tender_id)
            tenders.append(
                {
                    "tender_id": tender_id,
                    "title": title[:500],
                    "description": description or text,
                    "portal": self.portal_name,
                    "state": self.state,
                    "tender_url": url,
                    "published_date": None,
                    "closing_date": self._parse_date_token(closing_text),
                    "estimated_value": self._parse_value(text),
                    "categories": [],
                    "matched_keywords": [],
                    "raw_data": {
                        "source": "live_portal",
                        "source_url": url,
                        "scrape_method": "andhra_public_cards",
                        "procurement_id": procurement_id,
                        "tender_display_id": display_id,
                        "tender_number": tender_number,
                    },
                }
            )
        return tenders
