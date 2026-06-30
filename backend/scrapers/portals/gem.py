from typing import Any
import asyncio
import json
import re
import random
from datetime import date, datetime
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from ..base_scraper import BaseScraper, USER_AGENTS


class GeMScraper(BaseScraper):

    async def scrape(self, search_query: str | None = None) -> list[dict[str, Any]]:
        url = self.listing_urls[0]
        cfg = __import__("app.config", fromlist=["settings"]).settings()
        headers = {
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "application/json,text/html,*/*",
            "Accept-Language": "en-IN,en;q=0.9",
            "Referer": url,
            "X-Requested-With": "XMLHttpRequest",
        }
        tenders = []
        seen = set()
        chosen_pager: str | None = None
        async with httpx.AsyncClient(
            timeout=cfg["scraper_request_timeout_seconds"],
            follow_redirects=True,
            headers=headers,
            verify=False,
        ) as client:
            page = await client.get(url)
            page.raise_for_status()
            csrf_token = None
            csrf_match = re.search(r"csrf_bd_gem_nk['\"]?\s*:\s*['\"]([^'\"]+)['\"]", page.text)
            if csrf_match:
                csrf_token = csrf_match.group(1)
            if not csrf_token:
                meta_match = re.search(r'<meta[^>]+name=["\'"]csrf["\'"][^>]+content=["\'"]([^"\']+)["\'"]', page.text, re.IGNORECASE)
                if meta_match:
                    csrf_token = meta_match.group(1)
            if not csrf_token:
                page_soup = BeautifulSoup(page.text, "html.parser")
                csrf_input = page_soup.select_one('input[name*="csrf"]')
                if csrf_input:
                    csrf_token = csrf_input.get("value", "")
            if not csrf_token:
                raise RuntimeError("GeM bid CSRF token not found")

            for page_number in range(1, cfg["max_pages_per_portal"] + 1):
                docs = []
                page_payload = {}
                pager_candidates = [chosen_pager] if chosen_pager else self._gem_pager_candidates(page_number, cfg["gem_page_size"])
                for pager_name in [candidate for candidate in pager_candidates if candidate]:
                    try:
                        payload = self._gem_payload(page_number, cfg["gem_page_size"], pager_name)
                        response = await client.post(
                            "https://bidplus.gem.gov.in/all-bids-data",
                            data={"payload": json.dumps(payload), "csrf_bd_gem_nk": csrf_token},
                            headers=headers,
                        )
                        response.raise_for_status()
                        data = response.json()
                        inner = ((data.get("response") or {}).get("response") or {})
                        candidate_docs = inner.get("docs") or []
                        if candidate_docs:
                            docs = candidate_docs
                            page_payload = payload
                            if pager_name != "none":
                                chosen_pager = pager_name
                            break
                    except Exception as exc:
                        if page_number == 1:
                            print(f"GeM page style '{pager_name}' failed: {exc}")
                        continue
                if not docs:
                    break
                new_on_page = 0
                for doc in docs:
                    bid_id = self._first_doc_value(doc, "b_id", "id")
                    bid_number = self._first_doc_value(doc, "b_bid_number") or str(bid_id or "")
                    category = self._first_doc_value(doc, "b_category_name", "bd_category_name") or bid_number
                    buyer = self._first_doc_value(doc, "ba_official_details_minName", "ba_official_details_deptName")
                    if not bid_id or not category:
                        continue
                    tender_url = f"https://bidplus.gem.gov.in/showbidDocument/{bid_id}"
                    tender_id = self.generate_tender_id(str(bid_number), tender_url)
                    if tender_id in seen:
                        continue
                    seen.add(tender_id)
                    new_on_page += 1
                    title = f"{bid_number} - {category}"
                    description = self.clean_text(
                        " ".join(
                            str(item)
                            for item in [
                                bid_number,
                                category,
                                buyer,
                                self._first_doc_value(doc, "b_total_quantity"),
                            ]
                            if item not in (None, "")
                        )
                    )
                    tenders.append(
                        {
                            "tender_id": tender_id,
                            "title": title[:500],
                            "description": description,
                            "portal": self.portal_name,
                            "state": self.state,
                            "tender_url": tender_url,
                            "published_date": self._parse_iso_date(self._first_doc_value(doc, "final_start_date_sort")),
                            "closing_date": self._parse_iso_date(self._first_doc_value(doc, "final_end_date_sort")),
                            "estimated_value": None,
                            "categories": [],
                            "matched_keywords": [],
                            "raw_data": {
                                "source": "live_portal",
                                "source_url": url,
                                "stable_url": tender_url,
                                "scrape_method": "gem_json_api",
                                "search_term": "unfiltered_public_listing",
                                "page_number": page_number,
                                "pager_style": chosen_pager,
                                "page_payload": page_payload,
                                "bid_number": bid_number,
                                "buyer": buyer,
                            },
                        }
                    )

                    if cfg["max_tenders_per_portal"] and len(tenders) >= cfg["max_tenders_per_portal"]:
                        return tenders
                if new_on_page == 0:
                    break
                await asyncio.sleep(0.25)
        return tenders

    def _gem_pager_candidates(self, page_number: int, page_size: int) -> list[str]:
        if page_number == 1:
            return ["none", "page", "page_no", "offset", "param_page", "pagination"]
        return ["page", "page_no", "offset", "param_page", "pagination", "none"]

    def _gem_payload(self, page_number: int, page_size: int, pager_name: str) -> dict[str, Any]:
        offset = max(0, (page_number - 1) * page_size)
        payload: dict[str, Any] = {
            "param": {"searchBid": "", "searchType": "fullText"},
            "filter": {
                "bidStatusType": "ongoing_bids",
                "byType": "all",
                "highBidValue": "",
                "byEndDate": {"from": "", "to": ""},
                "sort": "Bid-End-Date-Oldest",
            },
        }
        if pager_name == "page":
            payload.update({"page": page_number, "pageSize": page_size, "size": page_size})
        elif pager_name == "page_no":
            payload.update({"page_no": page_number, "pageNo": page_number, "pageSize": page_size})
        elif pager_name == "offset":
            payload.update({"from": offset, "start": offset, "size": page_size, "rows": page_size})
        elif pager_name == "param_page":
            payload["param"].update({"page": page_number, "page_no": page_number, "pageSize": page_size, "limit": page_size})
        elif pager_name == "pagination":
            payload["pagination"] = {"page": page_number, "pageNo": page_number, "perPage": page_size, "size": page_size}
        return payload
