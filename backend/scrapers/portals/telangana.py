from typing import Any
import re

from ..base_scraper import BaseScraper


class TelanganaScraper(BaseScraper):

    async def scrape(self, search_query: str | None = None) -> list[dict[str, Any]]:
        url = "https://tender.telangana.gov.in/login.html"
        soup = await self.fetch_static(url)
        tenders = []
        seen = set()
        for block in soup.select(".update-nag, .updateNag"):
            tender_anchor = block.select_one(".tCurrent")
            if not tender_anchor:
                continue
            notice_anchor = block.select_one(".tUpcomingNo")
            anchors = block.select(".update-text a")
            desc_anchor = anchors[-1] if anchors else None
            procurement_match = re.search(r"viewtender\((\d+)\)", str(block), re.IGNORECASE)
            procurement_id = procurement_match.group(1) if procurement_match else None
            display_id = self.clean_text(tender_anchor.get_text(" "))
            notice_number = self.clean_text(notice_anchor.get_text(" ") if notice_anchor else "")
            description = self.clean_text(desc_anchor.get_text(" ") if desc_anchor else block.get_text(" "))
            title_text = self.clean_text((tender_anchor.get("title") or "").strip("()") or notice_number or description)
            split_values = [self.clean_text(item.get_text(" ")) for item in block.select(".update-split h4")]
            closing_date = self._parse_month_day_time(
                split_values[0] if len(split_values) > 0 else None,
                split_values[1] if len(split_values) > 1 else None,
                split_values[2] if len(split_values) > 2 else None,
            )
            if not display_id or not title_text:
                continue
            title = f"{display_id} - {title_text}"
            tender_id = self.generate_tender_id(display_id, procurement_id or notice_number)
            if tender_id in seen:
                continue
            seen.add(tender_id)
            tenders.append(
                {
                    "tender_id": tender_id,
                    "title": title[:500],
                    "description": description,
                    "portal": self.portal_name,
                    "state": self.state,
                    "tender_url": url,
                    "published_date": None,
                    "closing_date": closing_date,
                    "estimated_value": self._parse_value(description),
                    "categories": [],
                    "matched_keywords": [],
                    "raw_data": {
                        "source": "live_portal",
                        "source_url": url,
                        "scrape_method": "telangana_public_cards",
                        "procurement_id": procurement_id,
                        "tender_display_id": display_id,
                        "tender_number": notice_number,
                        "closing_text": " ".join(split_values),
                    },
                }
            )
        return tenders
