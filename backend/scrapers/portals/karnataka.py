from typing import Any
import asyncio
import re
import random
from datetime import date

import httpx
from bs4 import BeautifulSoup
from urllib.parse import urljoin

from ..base_scraper import BaseScraper, USER_AGENTS


class KarnatakaScraper(BaseScraper):

    async def scrape(self, search_query: str | None = None) -> list[dict[str, Any]]:
        cfg = __import__("app.config", fromlist=["settings"]).settings()
        headers = {
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-IN,en;q=0.9",
            "Origin": "https://kppp.karnataka.gov.in",
            "Referer": "https://kppp.karnataka.gov.in/",
            "Content-Type": "application/json",
        }
        base_api = "https://kppp.karnataka.gov.in/supplier-registration-service/v1/api"
        searches = [
            ("GOODS", "portal-service/search-eproc-tenders", "good"),
            ("WORKS", "portal-service/works/search-eproc-tenders", "work"),
            ("SERVICES", "portal-service/services/search-eproc-tenders", "service"),
        ]
        tenders = []
        seen = set()
        async with httpx.AsyncClient(
            timeout=cfg["scraper_request_timeout_seconds"],
            follow_redirects=True,
            headers=headers,
            verify=False,
        ) as client:
            for category, endpoint_path, detail_slug in searches:
                for page_index in range(cfg["max_pages_per_portal"]):
                    endpoint = f"{base_api}/{endpoint_path}?page={page_index}&size=100&order-by-tender-publish=true"
                    try:
                        response = await client.post(endpoint, json={"category": category, "status": "PUBLISHED", "tenderType": "OPEN"})
                        response.raise_for_status()
                        rows_payload = response.json()
                        rows = rows_payload
                        if isinstance(rows_payload, dict):
                            rows = rows_payload.get("content") or rows_payload.get("data") or rows_payload.get("result") or rows_payload.get("tenders") or []
                    except Exception as exc:
                        print(f"KPPP {category} page {page_index + 1} failed: {exc}")
                        break
                    if not rows:
                        break
                    new_on_page = 0
                    for row in (rows or []):
                        if not isinstance(row, dict):
                            continue
                        nit_id = self._first_doc_value(row, "nitId", "id")
                        tender_number = self._first_doc_value(row, "tenderNumber") or str(nit_id or "")
                        title_value = self._first_doc_value(row, "title", "description") or tender_number
                        if not nit_id or not title_value:
                            continue

                        full_view = {}
                        try:
                            detail_url = f"{base_api}/portal-service/{nit_id}/{detail_slug}-tender-full-view"
                            detail_response = await client.get(detail_url)
                            if detail_response.status_code == 200:
                                full_view = detail_response.json()
                        except Exception:
                            full_view = {}

                        schedule = full_view.get("tenderSchedule") if isinstance(full_view, dict) else {}
                        notice = full_view.get("noticeInvitingTenderDTO") if isinstance(full_view, dict) else {}
                        if not isinstance(schedule, dict):
                            schedule = {}
                        if not isinstance(notice, dict):
                            notice = {}

                        title = self.clean_text(f"{tender_number} - {schedule.get('title') or title_value}")
                        description = self.clean_text(
                            " ".join(
                                str(value)
                                for value in [
                                    schedule.get("description") or row.get("description"),
                                    schedule.get("deptName") or row.get("deptName"),
                                    schedule.get("locationName") or row.get("locationName"),
                                    schedule.get("categoryText") or row.get("categoryText"),
                                ]
                                if value not in (None, "")
                            )
                        )
                        published_date = self._parse_date_token(notice.get("publishedDate") or row.get("publishedDate") or row.get("tenderPublishedDate"))
                        closing_date = self._parse_date_token(notice.get("tenderReceiptClose") or row.get("tenderClosureDate") or row.get("closingDate"))
                        opening_date = self._parse_date_token(
                            notice.get("technicalBidOpen")
                            or notice.get("preQualificationBidOpen")
                            or notice.get("commercialBidOpen")
                            or row.get("tenderOpeningDate")
                        )
                        tender_url = "https://kppp.karnataka.gov.in/portal/searchTender/live"
                        tender_id = self.generate_tender_id(tender_number, str(nit_id))
                        if tender_id in seen:
                            continue
                        seen.add(tender_id)
                        new_on_page += 1
                        raw_data = {
                            "source": "live_portal",
                            "source_url": tender_url,
                            "stable_url": tender_url,
                            "scrape_method": "kppp_json_api",
                            "page_number": page_index + 1,
                            "nit_id": nit_id,
                            "tender_number": tender_number,
                            "kppp_category": category,
                            "department": schedule.get("deptName") or row.get("deptName"),
                            "location": schedule.get("locationName") or row.get("locationName"),
                        }
                        if opening_date:
                            raw_data["opening_date"] = opening_date.isoformat()
                        tenders.append(
                            {
                                "tender_id": tender_id,
                                "title": title[:500],
                                "description": description or title,
                                "portal": self.portal_name,
                                "state": self.state,
                                "tender_url": tender_url,
                                "published_date": published_date,
                                "closing_date": closing_date,
                                "estimated_value": self._parse_value(str(schedule.get("ecv") or row.get("ecv") or "")),
                                "categories": [],
                                "matched_keywords": [],
                                "raw_data": raw_data,
                            }
                        )
                        if cfg["max_tenders_per_portal"] and len(tenders) >= cfg["max_tenders_per_portal"]:
                            return tenders
                    if new_on_page == 0:
                        break
                    await asyncio.sleep(0.2)
        return tenders
