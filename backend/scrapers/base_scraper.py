import asyncio
import hashlib
import json
import random
import re
from datetime import date, datetime, timedelta
from html import unescape
from typing import Any
from urllib.parse import urlencode, urljoin

import httpx
from bs4 import BeautifulSoup

from app.config import settings


USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 Version/17.5 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0",
]


DATE_PATTERN = re.compile(
    r"\b(?:\d{1,2}[-/]\d{1,2}[-/]\d{2,4}|\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}[-/][A-Za-z]{3}[-/]\d{2,4})"
    r"(?:\s+\d{1,2}:\d{2}(?::\d{2})?\s*(?:AM|PM)?)?\b",
    re.IGNORECASE,
)
BRACKET_PATTERN = re.compile(r"\[([^\]]{8,500})\]")
PUBLISHED_LABELS = (
    "published date",
    "publish date",
    "date of publish",
    "start date",
    "bid start date",
    "bid submission start",
    "document download start",
    "posted date",
    "प्रकाशित दिनांक",
    "प्रकाशित तिथि",
    "प्रकाशन दिनांक",
)
CLOSING_LABELS = (
    "closing date",
    "bid closing date",
    "bid submission closing date",
    "bid submission end date",
    "submission closing date",
    "submission end date",
    "end date",
    "due date",
    "last date",
    "last date of submission",
    "समाप्ति तिथि",
    "अंतिम तिथि",
    "अंतिम दिनांक",
    "बंद दिनांक",
    "निविदा समाप्ती दिनांक",
    "सादरीकरणाची अंतिम तारीख",
)
OPENING_LABELS = (
    "opening date",
    "bid opening date",
    "technical bid opening date",
    "date of opening",
    "open date",
    "खुलने की तिथि",
    "उघडण्याची तारीख",
    "उघडण्याचा दिनांक",
    "निविदा उघडण्याची तारीख",
)
DETAIL_LINK_SIGNALS = (
    "directlink",
    "tenderdetails",
    "tenderdetail",
    "viewtender",
    "view-tender",
    "showbiddocument",
    "bid-detail",
    "bid_no",
    "bidnumber",
    "nit",
    "rfp",
    "rfq",
    "sp=",
    "component=",
)
VALUE_PATTERN = re.compile(r"(?:rs\.?|inr|₹)\s*([0-9][0-9,]*(?:\.\d+)?)", re.IGNORECASE)
FORM_OR_NAV_TEXT = [
    "-select-",
    "active tenders",
    "tender type *",
    "tenders by organisation",
    "tenders by location",
    "tenders by classification",
    "tenders in archive",
    "cancelled tenders",
    "results of tenders",
    "organisation -select-",
    "product category -select-",
    "sub division -select-",
    "screen reader access",
    "visitor no:",
    "designed, developed and hosted",
    "contents owned and maintained",
    "technical issues redressal",
    "appellate authority",
    "online payment",
    "help desk",
    "web announcements",
    "latest announcements",
    "download & fill the form",
    "registration number updation",
    "pan number updation",
    "new user id",
    "forget user id",
    "forgot user id",
    "user acceptance",
    "workflow configuration",
    "company updation",
    "company name updation",
    "captcha",
    "login",
    "advanced search",
    "terms and conditions",
    "privacy policy",
    "site map",
]
NAV_TITLES = {
    "back",
    "home",
    "reports",
    "login",
    "search",
    "submit",
    "reset",
    "events",
    "cppp",
    "railways contracts",
    "view tender information",
    "active tenders",
    "cancelled tenders",
    "tenders in archive",
    "tenders by classification",
    "tenders by organisation",
    "tenders by location",
}
GENERIC_TITLES = {"view tender information", "more tenders"}
NON_TENDER_TITLE_MARKERS = (
    "business opportunities",
    "important notice",
    "advisory",
    "payment processing",
    "bidder registration",
    "vendor registration",
    "terms and conditions",
    "privacy policy",
    "contact us",
    "help desk",
)
TENDER_SIGNALS = [
    "tender",
    "bid",
    "procurement",
    "purchase",
    "supply",
    "work",
    "nit",
    "rfp",
    "rfq",
    "quotation",
    "auction",
    "contract",
    "निविदा",
    "बोली",
    "खरीद",
    "खरेदी",
    "पुरवठा",
    "आपूर्ति",
    "काम",
    "करार",
]
DETAIL_ENRICHMENT_LIMIT = 15
DEVANAGARI_PATTERN = re.compile(r"[\u0900-\u097F]")


def detect_regional_language(text: str) -> str:
    if not DEVANAGARI_PATTERN.search(text or ""):
        return "en"
    marathi_markers = ("निविदा", "खरेदी", "पुरवठा", "उघडण्याची", "दिनांक", "सादरीकरणाची", "कॅमेरा")
    hindi_markers = ("निविदा", "खरीद", "आपूर्ति", "खुलने", "तिथि", "बोली", "कैमरा")
    if any(marker in text for marker in marathi_markers):
        return "mr"
    if any(marker in text for marker in hindi_markers):
        return "hi"
    return "hi"


class BaseScraper:
    def __init__(
        self,
        portal_name: str,
        base_url: str,
        state: str,
        use_playwright: bool = False,
        listing_urls: list[str] | None = None,
    ):
        self.portal_name = portal_name
        self.base_url = base_url
        self.state = state
        self.use_playwright = use_playwright
        self.listing_urls = listing_urls or [base_url]

    def generate_tender_id(self, title: str, date_value: str | None = None) -> str:
        raw = f"{self.portal_name}|{title}|{date_value or ''}"
        return hashlib.sha256(raw.encode()).hexdigest()[:24]

    def clean_text(self, text: str | None) -> str:
        return " ".join((text or "").strip().split())

    def sample_tender(self) -> dict[str, Any]:
        title = f"{self.portal_name} surveillance equipment notice for thermal camera and communication equipment"
        matched, categories = [], []
        return {
            "tender_id": self.generate_tender_id(title, date.today().isoformat()),
            "title": title,
            "description": title,
            "portal": self.portal_name,
            "state": self.state,
            "tender_url": self.base_url,
            "published_date": date.today(),
            "closing_date": date.today() + timedelta(days=random.randint(10, 30)),
            "estimated_value": None,
            "categories": categories,
            "matched_keywords": matched,
            "raw_data": {"source": "sample_fallback", "source_url": self.base_url, "stable_url": self.base_url, "scrape_method": "sample_fallback"},
        }

    async def fetch_static(self, url: str) -> BeautifulSoup:
        cfg = settings()
        proxy_url = None
        if cfg["scraper_api_key"]:
            proxy_url = "https://api.scraperapi.com/?" + urlencode(
                {
                    "api_key": cfg["scraper_api_key"],
                    "url": url,
                    "country_code": "in",
                    "keep_headers": "true",
                    "retry_404": "true",
                    "render": "false",
                }
            )
        request_targets: list[tuple[str, bool]] = []
        if cfg["use_proxy"] and proxy_url:
            request_targets.append((proxy_url, True))
        request_targets.append((url, False))
        if proxy_url and not cfg["use_proxy"] and cfg["scraper_proxy_fallback"]:
            request_targets.append((proxy_url, True))

        last_error = None
        for attempt in range(cfg["scraper_retries"]):
            for target_url, proxy_used in request_targets:
                headers = {
                    "User-Agent": random.choice(USER_AGENTS),
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "en-IN,en;q=0.9",
                    "Cache-Control": "no-cache",
                    "Pragma": "no-cache",
                    "Referer": self.base_url,
                }
                try:
                    async with httpx.AsyncClient(
                        timeout=cfg["scraper_request_timeout_seconds"],
                        follow_redirects=True,
                        headers=headers,
                        verify=False,
                    ) as client:
                        response = await client.get(target_url)
                        if response.status_code in {403, 429, 503}:
                            mode = "proxy" if proxy_used else "direct"
                            raise httpx.HTTPStatusError(f"{mode} blocked with {response.status_code}", request=response.request, response=response)
                        if response.status_code in {404, 410}:
                            raise RuntimeError(f"portal page returned {response.status_code}; listing URL may have changed")
                        response.raise_for_status()
                        soup = BeautifulSoup(response.text, "html.parser")
                        if proxy_used:
                            marker = soup.new_tag("meta")
                            marker["name"] = "tenderwatch-fetch-mode"
                            marker["content"] = "scraperapi_proxy"
                            if soup.head:
                                soup.head.append(marker)
                        return soup
                except Exception as exc:
                    last_error = exc
            await asyncio.sleep(1.5 * (attempt + 1))
        error_text = str(last_error) or (last_error.__class__.__name__ if last_error else "unknown error")
        raise RuntimeError(f"{self.portal_name} failed after retries: {error_text}")

    async def fetch_tapestry_submit(self, url: str, submit_name: str = "LinkSubmit_0") -> BeautifulSoup:
        """
        Submit a NIC/Apache Tapestry tender listing form while preserving the
        fresh session cookie from the first page load.
        """
        headers = {
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-IN,en;q=0.9",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "Referer": self.base_url,
        }
        async with httpx.AsyncClient(
            timeout=settings()["scraper_request_timeout_seconds"],
            follow_redirects=True,
            headers=headers,
            verify=False,
        ) as client:
            response = await client.get(url)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")
            form = None
            for candidate in soup.select("form"):
                inputs_text = " ".join(
                    f"{field.get('name') or ''}={field.get('value') or ''}".lower()
                    for field in candidate.select("input")
                ).lower()
                if any(marker in inputs_text for marker in ("listtendersbydate", "linksubmit", "submitname", "submitmode", "t:formdata")):
                    form = candidate
                    break
            if form is None:
                forms = soup.select("form")
                if forms:
                    form = forms[0]
                else:
                    raise RuntimeError(f"No Tapestry form found on {url}")

            data = {}
            for field in form.select("input"):
                name = field.get("name")
                if name:
                    data[name] = field.get("value", "")
            data["submitname"] = submit_name
            data.setdefault("submitmode", "")
            if "t:submit" in data:
                data["t:submit"] = f'["{submit_name}","{submit_name}"]'
            action = urljoin(str(response.url), form.get("action") or str(response.url))
            submitted = await client.post(
                action,
                data=data,
                headers={**headers, "Referer": str(response.url), "Content-Type": "application/x-www-form-urlencoded"},
            )
            submitted.raise_for_status()
            return BeautifulSoup(submitted.text, "html.parser")

    async def fetch_dynamic(self, url: str) -> BeautifulSoup:
        try:
            from playwright.async_api import async_playwright
        except Exception as exc:
            raise RuntimeError("Playwright browser scraper is not installed") from exc

        try:
            async with async_playwright() as playwright:
                browser = await playwright.chromium.launch(headless=True)
                context = await browser.new_context(user_agent=random.choice(USER_AGENTS))
                page = await context.new_page()
                await page.goto(url, wait_until="networkidle", timeout=settings()["scraper_request_timeout_seconds"] * 1000)
                html = await page.content()
                await browser.close()
                return BeautifulSoup(html, "html.parser")
        except Exception as exc:
            raise RuntimeError(f"dynamic browser scrape failed: {exc}") from exc

    async def soup(self, url: str) -> BeautifulSoup:
        use_browser = self.use_playwright and settings()["use_playwright"]
        return await (self.fetch_dynamic(url) if use_browser else self.fetch_static(url))

    async def scrape(self) -> list[dict[str, Any]]:
        raise NotImplementedError


class GenericTenderScraper(BaseScraper):
    async def scrape(self) -> list[dict[str, Any]]:
        """
        Master dispatch for all portals.
        Dedicated APIs and session-based forms run before the generic fallback.
        """
        if self.portal_name == "GeM":
            try:
                result = await self._scrape_gem_api()
                if result:
                    return result
            except Exception as exc:
                print(f"GeM API failed: {exc}")
        if self.portal_name == "Karnataka eProcurement":
            try:
                result = await self._scrape_kppp_api()
                if result:
                    return result
            except Exception as exc:
                print(f"KPPP API failed: {exc}")
        if self.portal_name == "Andhra Pradesh eProcurement":
            try:
                result = await self._scrape_andhra_public_page()
                if result:
                    return result
            except Exception as exc:
                print(f"Andhra scrape failed: {exc}")
        if self.portal_name == "Telangana Tenders":
            try:
                result = await self._scrape_telangana_public_page()
                if result:
                    return result
            except Exception as exc:
                print(f"Telangana scrape failed: {exc}")
        if self.portal_name == "nProcure":
            try:
                result = await self._scrape_nprocure_closing_reports()
                if result:
                    return result
            except Exception as exc:
                print(f"nProcure scrape failed: {exc}")

        specific_scrapers = {
            "CPPP": self._scrape_cppp,
            "IREPS": self._scrape_ireps,
            "Bihar eProcurement": self._scrape_bihar,
            "GePNIC": self._scrape_gepnic,
        }
        if self.portal_name in specific_scrapers:
            try:
                result = await specific_scrapers[self.portal_name]()
                if result:
                    return result
            except Exception as exc:
                print(f"{self.portal_name} scrape failed: {exc}")

        nic_portals = {
            "Defence eProcurement",
            "Coal India Tenders",
            "MahaTenders",
            "Tamil Nadu Tenders",
            "UP eTender",
            "Rajasthan eProcurement",
            "MP Tenders",
            "Haryana eTenders",
            "Punjab eProcurement",
            "Kerala eTenders",
            "West Bengal Tenders",
            "Odisha Tenders",
            "Jharkhand Tenders",
            "Assam Tenders",
        }
        if self.portal_name in nic_portals:
            try:
                result = await self._scrape_nic_tapestry()
                if result:
                    return result
            except Exception as exc:
                print(f"{self.portal_name} NIC Tapestry failed: {exc}")

        failures = []
        all_tenders = []
        seen_ids = set()
        for url in self.listing_urls:
            url_tenders = []

            try:
                soup = await self.fetch_static(url)
                parsed = self._parse_candidates(soup, source_url=url, scrape_method="static_html")
                await self._enrich_missing_schedule(parsed)
                url_tenders.extend(parsed)
                if not parsed and self._is_tapestry_tender_listing(url, soup):
                    for submit_name in ("LinkSubmit_0", "LinkSubmit_1"):
                        try:
                            submitted_soup = await self.fetch_tapestry_submit(url, submit_name)
                            submitted = self._parse_candidates(
                                submitted_soup,
                                source_url=url,
                                scrape_method=f"tapestry_form_{submit_name}",
                            )
                            await self._enrich_missing_schedule(submitted)
                            url_tenders.extend(submitted)
                            if submitted:
                                break
                        except Exception as form_exc:
                            failures.append(f"{url} tapestry_{submit_name}: {form_exc}")
            except Exception as exc:
                failures.append(f"{url} static_html: {exc}")

            if self.use_playwright and settings()["use_playwright"]:
                try:
                    soup = await self.fetch_dynamic(url)
                    parsed = self._parse_candidates(soup, source_url=url, scrape_method="dynamic_browser")
                    await self._enrich_missing_schedule(parsed)
                    url_tenders.extend(parsed)
                except Exception as exc:
                    failures.append(f"{url} dynamic_browser: {exc}")

            if url_tenders:
                for tender in url_tenders:
                    if tender["tender_id"] not in seen_ids:
                        seen_ids.add(tender["tender_id"])
                        all_tenders.append(tender)

        if all_tenders:
            return all_tenders

        if failures and not settings()["enable_sample_fallback"]:
            raise RuntimeError("; ".join(failures[:3]))

        if settings()["enable_sample_fallback"]:
            return [self.sample_tender()]

        return []

    def _first_doc_value(self, doc: dict[str, Any], *keys: str):
        for key in keys:
            value = doc.get(key)
            if isinstance(value, list):
                value = value[0] if value else None
            if value not in (None, ""):
                return value
        return None

    def _parse_iso_date(self, value: Any):
        if not value:
            return None
        raw = str(value).replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(raw).date()
        except ValueError:
            return self._parse_date_token(str(value))

    async def _scrape_gem_api(self) -> list[dict[str, Any]]:
        url = self.listing_urls[0]
        cfg = settings()
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
            timeout=settings()["scraper_request_timeout_seconds"],
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
                meta_match = re.search(r'<meta[^>]+name=["\']csrf["\'][^>]+content=["\']([^"\']+)["\']', page.text, re.IGNORECASE)
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
                    matched, categories = [], []
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
                            "categories": categories,
                            "matched_keywords": matched,
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

    async def _scrape_nprocure_closing_reports(self) -> list[dict[str, Any]]:
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
        for raw_date, count in tender_counts.items():
            parsed_date = self._parse_iso_date(raw_date)
            if parsed_date and parsed_date >= today and int(count or 0) > 0:
                dated_counts.append((parsed_date, int(count)))
        if not dated_counts:
            for raw_date, count in tender_counts.items():
                parsed_date = self._parse_iso_date(raw_date)
                if parsed_date and int(count or 0) > 0:
                    dated_counts.append((parsed_date, int(count)))
        dated_counts.sort(key=lambda item: item[0])

        tenders = []
        seen = set()
        async with httpx.AsyncClient(
            timeout=settings()["scraper_request_timeout_seconds"],
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

    async def _fetch_nprocure_closing_report(self, client: httpx.AsyncClient, report_url: str, requested_date: str) -> BeautifulSoup:
        cfg = settings()
        target_url = report_url
        if cfg["use_proxy"] and cfg["scraper_api_key"]:
            target_url = "https://api.scraperapi.com/?" + urlencode(
                {
                    "api_key": cfg["scraper_api_key"],
                    "url": report_url,
                    "country_code": "in",
                    "keep_headers": "true",
                    "retry_404": "true",
                }
            )
        response = await client.post(target_url, data={"requestedDate": requested_date})
        response.raise_for_status()
        return BeautifulSoup(response.text, "html.parser")

    def _parse_nprocure_closing_report(self, soup: BeautifulSoup, report_url: str, calendar_url: str, closing_day: date) -> list[dict[str, Any]]:
        tables = soup.select("table")
        if len(tables) < 2:
            return []

        tenders = []
        current_department = "nProcure"
        for row in tables[1].select("tr"):
            cells = [self.clean_text(cell.get_text(" ")) for cell in row.find_all(["td", "th"])]
            if not cells:
                continue
            if cells[0].lower() in {"sr. no.", "sr no.", "sr no"}:
                continue
            if len(cells) == 1:
                current_department = cells[0]
                continue
            if len(cells) < 4 or not cells[0].isdigit():
                continue

            _serial, tender_number, notice_number, closing_text = cells[:4]
            closing_date = self._parse_date_token(closing_text) or closing_day
            title = self.clean_text(f"{notice_number} - {current_department}")[:500]
            description = self.clean_text(
                f"{current_department} | Tender ID {tender_number} | IFB/Tender Notice Number {notice_number} | Last Date & Time of Bid Submission {closing_text}"
            )
            matched, categories = [], []
            tender_id = self.generate_tender_id(f"nprocure-{tender_number}", closing_text)
            tenders.append(
                {
                    "tender_id": tender_id,
                    "title": title,
                    "description": description,
                    "portal": self.portal_name,
                    "state": self.state,
                    "tender_url": calendar_url,
                    "published_date": None,
                    "closing_date": closing_date,
                    "estimated_value": None,
                    "categories": categories,
                    "matched_keywords": matched,
                    "raw_data": {
                        "source": "live_portal",
                        "source_url": report_url,
                        "calendar_url": calendar_url,
                        "scrape_method": "nprocure_closing_report",
                        "tender_number": tender_number,
                        "tender_display_id": tender_number,
                        "procurement_id": notice_number,
                        "department": current_department,
                        "closing_datetime": closing_text,
                    },
                }
            )
        return tenders

    def _parse_month_day_time(self, month: str | None, day_value: str | None, time_value: str | None):
        month = self.clean_text(month)
        day_value = self.clean_text(day_value)
        time_value = self.clean_text(time_value)
        if not month or not day_value:
            return None
        current_year = date.today().year
        for fmt in ("%d %B %Y %I:%M %p", "%d %b %Y %I:%M %p", "%d %B %Y", "%d %b %Y"):
            try:
                raw = f"{day_value} {month} {current_year} {time_value}".strip()
                parsed = datetime.strptime(raw, fmt).date()
                if parsed < date.today() - timedelta(days=30):
                    parsed = parsed.replace(year=parsed.year + 1)
                return parsed
            except ValueError:
                continue
        return None

    async def _scrape_telangana_public_page(self) -> list[dict[str, Any]]:
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
            matched, categories = [], []
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
                    "categories": categories,
                    "matched_keywords": matched,
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

    async def _scrape_andhra_public_page(self) -> list[dict[str, Any]]:
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
            matched, categories = [], []
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
                    "categories": categories,
                    "matched_keywords": matched,
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

    async def _scrape_kppp_api(self) -> list[dict[str, Any]]:
        cfg = settings()
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
            timeout=settings()["scraper_request_timeout_seconds"],
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
                        matched, keyword_categories = [], []
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
                                "categories": keyword_categories,
                                "matched_keywords": matched,
                                "raw_data": raw_data,
                            }
                        )
                        if cfg["max_tenders_per_portal"] and len(tenders) >= cfg["max_tenders_per_portal"]:
                            return tenders
                    if new_on_page == 0:
                        break
                    await asyncio.sleep(0.2)
        return tenders

    async def _scrape_cppp(self) -> list[dict[str, Any]]:
        return await self._scrape_nic_tapestry()

    async def _scrape_gepnic(self) -> list[dict[str, Any]]:
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

    async def _scrape_bihar(self) -> list[dict[str, Any]]:
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
            timeout=settings()["scraper_request_timeout_seconds"],
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

    async def _scrape_ireps(self) -> list[dict[str, Any]]:
        login_url = "https://www.ireps.gov.in/epsn/guestLogin.do"
        headers = {
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-IN,en;q=0.9",
            "Referer": login_url,
        }
        tenders = []
        seen = set()
        async with httpx.AsyncClient(
            timeout=settings()["scraper_request_timeout_seconds"],
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

    async def _scrape_nic_tapestry(self) -> list[dict[str, Any]]:
        cfg = settings()
        tenders = []
        seen = set()
        for nic_url in self.listing_urls:
            empty_or_duplicate_pages = 0
            for page_index in range(cfg["max_pages_per_portal"]):
                submit_name = f"LinkSubmit_{page_index}"
                try:
                    soup = await self.fetch_tapestry_submit(nic_url, submit_name)
                    parsed = self._parse_candidates(
                        soup,
                        source_url=nic_url,
                        scrape_method=f"nic_tapestry_{submit_name}",
                    )
                    await self._enrich_missing_schedule(parsed)
                except Exception as exc:
                    print(f"{self.portal_name} Tapestry {submit_name} failed: {exc}")
                    if page_index == 0:
                        continue
                    break

                new_on_page = 0
                for tender in parsed:
                    raw_data = dict(tender.get("raw_data") or {})
                    stable_url = raw_data.get("stable_url") or (tender.get("tender_url") or nic_url).split("?")[0]
                    raw_data["stable_url"] = stable_url
                    raw_data["source_url"] = raw_data.get("source_url") or nic_url
                    raw_data["page_number"] = page_index + 1
                    tender["raw_data"] = raw_data
                    if tender["tender_id"] in seen:
                        continue
                    seen.add(tender["tender_id"])
                    new_on_page += 1
                    tenders.append(tender)
                    if cfg["max_tenders_per_portal"] and len(tenders) >= cfg["max_tenders_per_portal"]:
                        return tenders

                if new_on_page == 0:
                    empty_or_duplicate_pages += 1
                else:
                    empty_or_duplicate_pages = 0
                if empty_or_duplicate_pages >= 2:
                    break
                await asyncio.sleep(0.2)

            try:
                soup = await self.fetch_static(nic_url)
                parsed = self._parse_candidates(soup, source_url=nic_url, scrape_method="nic_static_fallback")
                await self._enrich_missing_schedule(parsed)
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

    def _is_tapestry_tender_listing(self, url: str, soup: BeautifulSoup) -> bool:
        lowered_url = (url or "").lower()
        if "frontendlisttendersbydate" not in lowered_url:
            return False
        page_text = self.clean_text(soup.get_text(" ")).lower()
        return "closing within 7 days" in page_text or "listtendersbydate" in page_text

    def _parse_date_token(self, raw: str | None):
        if not raw:
            return None
        date_match = DATE_PATTERN.search(self.clean_text(raw))
        if not date_match:
            return None
        raw_date = date_match.group(0).split()[0]
        for fmt in ("%d-%b-%Y", "%d-%b-%y", "%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d", "%Y/%m/%d", "%d-%m-%y", "%d/%m/%y"):
            try:
                return datetime.strptime(raw_date, fmt).date()
            except ValueError:
                continue
        return None

    def _parse_all_dates(self, text: str) -> list[date]:
        dates = []
        for match in DATE_PATTERN.finditer(text):
            parsed = self._parse_date_token(match.group(0))
            if parsed:
                dates.append(parsed)
        return dates

    def _parse_date(self, text: str, index: int = -1):
        matches = self._parse_all_dates(text)
        if not matches:
            return None
        return matches[index]

    def _labeled_date(self, text: str, labels: tuple[str, ...]):
        label_source = "|".join(re.escape(label) for label in labels)
        pattern = re.compile(rf"(?:{label_source}).{{0,120}}?(?P<date>{DATE_PATTERN.pattern})", re.IGNORECASE)
        match = pattern.search(text)
        return self._parse_date_token(match.group("date")) if match else None

    def _extract_schedule(self, text: str) -> dict[str, date | None]:
        dates = self._parse_all_dates(text)
        published_date = self._labeled_date(text, PUBLISHED_LABELS)
        closing_date = self._labeled_date(text, CLOSING_LABELS)
        opening_date = self._labeled_date(text, OPENING_LABELS)

        if len(dates) >= 3:
            published_date = published_date or dates[0]
            closing_date = closing_date or dates[1]
            opening_date = opening_date or dates[2]
        elif len(dates) == 2:
            published_date = published_date or dates[0]
            closing_date = closing_date or dates[1]
        elif len(dates) == 1:
            single_date = dates[0]
            if not published_date and not closing_date and not opening_date:
                closing_date = single_date

        return {
            "published_date": published_date,
            "closing_date": closing_date,
            "opening_date": opening_date,
        }

    async def _enrich_missing_schedule(self, tenders: list[dict[str, Any]]) -> None:
        for tender in tenders[:DETAIL_ENRICHMENT_LIMIT]:
            raw_data = dict(tender.get("raw_data") or {})
            has_opening = bool(raw_data.get("opening_date"))
            if tender.get("closing_date") and has_opening:
                continue

            detail_url = tender.get("tender_url")
            source_url = raw_data.get("source_url")
            if not detail_url or detail_url == source_url:
                continue

            try:
                detail_soup = await self.fetch_static(detail_url)
                detail_text = self.clean_text(detail_soup.get_text(" "))
                schedule = self._extract_schedule(detail_text)
                document_urls = self._extract_document_links(detail_soup, detail_url)
            except Exception as exc:
                raw_data["detail_enrichment_status"] = "failed"
                raw_data["detail_enrichment_error"] = str(exc)[:180]
                tender["raw_data"] = raw_data
                continue

            if schedule["published_date"] and not tender.get("published_date"):
                tender["published_date"] = schedule["published_date"]
            if schedule["closing_date"] and not tender.get("closing_date"):
                tender["closing_date"] = schedule["closing_date"]
            if schedule["opening_date"] and not raw_data.get("opening_date"):
                raw_data["opening_date"] = schedule["opening_date"].isoformat()
            if document_urls:
                existing_docs = raw_data.get("document_urls") or []
                raw_data["document_urls"] = list(dict.fromkeys([*existing_docs, *document_urls]))
            raw_data["detail_enrichment_status"] = "checked"
            tender["raw_data"] = raw_data

    def _extract_document_links(self, soup: BeautifulSoup, source_url: str) -> list[str]:
        document_exts = (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".zip", ".rar", ".csv")
        urls = []
        for anchor in soup.select("a[href]"):
            href = self.clean_text(anchor.get("href"))
            if not href or href.lower().startswith(("javascript:", "#", "mailto:", "tel:")):
                continue
            text = self.clean_text(anchor.get_text(" ")).lower()
            absolute = urljoin(source_url, href)
            lowered = absolute.lower().split("?", 1)[0]
            if lowered.endswith(document_exts) or any(marker in text for marker in ("download", "boq", "nit", "document", "corrigendum", "specification")):
                urls.append(absolute)
        return list(dict.fromkeys(urls))

    def _parse_value(self, text: str):
        match = VALUE_PATTERN.search(text)
        if not match:
            return None
        try:
            return float(match.group(1).replace(",", ""))
        except ValueError:
            return None

    def _looks_like_tender(self, text: str, title: str, href: str) -> bool:
        lowered = f"{title} {text} {href}".lower()
        href_lower = (href or "").lower()
        has_date = bool(DATE_PATTERN.search(text))
        has_signal = any(signal in lowered for signal in TENDER_SIGNALS)
        has_detail_link = bool(href) and not href.lower().startswith(("javascript:", "#"))
        has_tender_detail_link = has_detail_link and any(signal in href_lower for signal in DETAIL_LINK_SIGNALS)
        generic_page = any(
            marker in lowered
            for marker in [
                "page=home",
                "webannouncements",
                "view_news",
                "/news/",
                "gem.gov.in/cppp",
                "gem.gov.in/view_contracts",
                "mkp.gem.gov.in",
                "services#!/browse",
                "advance-search",
                "all-bids",
                "bidder-registration",
                "anonymsearchpo.do",
                "frontendtendersby",
                "frontendcancelledtenders",
                "frontendtendersearch",
                "frontendarchive",
                "gepnicreports",
                "business opportunities",
                "important notice",
                "payment process",
                "bidder-registration",
                "seller registration",
                "buyer organisation",
            ]
        )
        non_tender_title = any(marker in (title or "").lower() for marker in NON_TENDER_TITLE_MARKERS)
        return not generic_page and not non_tender_title and has_signal and (has_date or has_tender_detail_link)

    def _extract_url_from_text(self, value: str | None, source_url: str):
        if not value:
            return None

        cleaned = unescape(value).replace("\\/", "/").strip()
        raw_candidates = re.findall(r"https?://[^\s'\"<>);]+", cleaned, flags=re.IGNORECASE)
        raw_candidates.extend(re.findall(r"['\"]([^'\"]{4,800})['\"]", cleaned))

        for candidate in raw_candidates:
            candidate = unescape(candidate).replace("\\/", "/").strip().rstrip(");,")
            lowered = candidate.lower()
            if not candidate or lowered.startswith(("javascript:", "#", "mailto:", "tel:")):
                continue
            is_urlish = candidate.startswith(("http://", "https://", "/", "?", "./", "../")) or "?" in candidate
            has_detail_signal = any(signal in lowered for signal in DETAIL_LINK_SIGNALS)
            if is_urlish and (has_detail_signal or candidate.startswith(("http://", "https://", "/", "?", "./", "../"))):
                return urljoin(source_url, candidate)

        return None

    def _resolve_anchor_url(self, anchor, source_url: str):
        href = self.clean_text(anchor.get("href")) if anchor else ""
        if href and not href.lower().startswith(("javascript:", "#", "mailto:", "tel:")):
            return urljoin(source_url, href)

        for attr in ("onclick", "data-href", "data-url", "data-target", "data-link", "href"):
            resolved = self._extract_url_from_text(anchor.get(attr) if anchor else "", source_url)
            if resolved:
                return resolved

        return None

    def _best_tender_url(self, block, source_url: str):
        anchors = block.find_all("a", href=True) if hasattr(block, "find_all") else []
        if getattr(block, "name", None) == "a" and block.has_attr("href"):
            anchors = [block]
        if not anchors:
            return None

        ranked = []
        for anchor in anchors:
            resolved = self._resolve_anchor_url(anchor, source_url)
            if not resolved:
                continue
            anchor_text = self.clean_text(anchor.get_text(" "))
            candidate_text = f"{resolved} {anchor_text} {anchor.get('title') or ''} {anchor.get('aria-label') or ''}".lower()
            score = sum(3 for signal in DETAIL_LINK_SIGNALS if signal in candidate_text)
            score += 2 if any(word in anchor_text.lower() for word in ("view", "open", "detail", "nit", "download")) else 0
            if any(fragment in candidate_text for fragment in ("page=home", "frontendtendersby", "frontendcancelledtenders", "frontendarchive")):
                score -= 5
            ranked.append((score, resolved))

        if not ranked:
            return None
        ranked.sort(key=lambda item: item[0], reverse=True)
        return ranked[0][1]

    def _extract_title(self, text: str, link_text: str, link_title: str, aria_title: str) -> str:
        for match in BRACKET_PATTERN.findall(text):
            cleaned = self.clean_text(match)
            lowered = cleaned.lower()
            if cleaned and lowered not in NAV_TITLES and lowered not in GENERIC_TITLES and not DATE_PATTERN.search(cleaned):
                return cleaned

        for fallback in (link_title, aria_title, link_text):
            lowered = fallback.lower()
            if fallback and lowered not in NAV_TITLES and lowered not in GENERIC_TITLES and not DATE_PATTERN.search(fallback):
                return fallback

        for fragment in re.split(r"\s{2,}|\|", text):
            cleaned = self.clean_text(fragment)
            lowered = cleaned.lower()
            if len(cleaned) >= 18 and lowered not in NAV_TITLES and not DATE_PATTERN.search(cleaned):
                return cleaned

        return text

    def _candidate_blocks(self, soup: BeautifulSoup):
        tender_rows = soup.select("table.list_table tr.even, table.list_table tr.odd, tr.even_row, tr.odd_row")
        if tender_rows:
            return tender_rows

        table_rows = [
            row
            for row in soup.select("table tr")
            if len(row.find_all(["td", "th"])) >= 2 and any(signal in row.get_text(" ").lower() for signal in TENDER_SIGNALS)
        ]
        if table_rows:
            return table_rows

        selectors = [
            ".bid-list-item",
            ".bid-card",
            ".tenderRow",
            ".list-item",
            "li",
            "article",
        ]
        blocks = []
        for selector in selectors:
            blocks.extend(soup.select(selector))
        if not blocks:
            blocks = soup.find_all("a", href=True)
        return blocks

    def _parse_candidates(self, soup: BeautifulSoup, source_url: str, scrape_method: str = "static_html") -> list[dict[str, Any]]:
        tenders = []
        seen = set()
        for block in self._candidate_blocks(soup):
            text = self.clean_text(block.get_text(" "))
            link = block.find("a", href=True) if hasattr(block, "find") else None
            if not link and getattr(block, "name", None) == "a" and block.has_attr("href"):
                link = block
            link_text = self.clean_text(link.get_text(" ")) if link else ""
            title_attr = self.clean_text(link.get("title")) if link else ""
            aria_attr = self.clean_text(link.get("aria-label")) if link else ""
            title = self._extract_title(text, link_text, title_attr, aria_attr)
            href = self.clean_text(link.get("href")) if link else ""
            detail_url = self._best_tender_url(block, source_url)
            filter_href = detail_url or href
            lowered_text = text.lower()
            lowered_title = title.lower()
            if (
                len(text) < 18
                or len(text) > 1400
                or lowered_title in NAV_TITLES
                or any(fragment in lowered_text for fragment in FORM_OR_NAV_TEXT)
                or not self._looks_like_tender(text, title, filter_href)
            ):
                continue
            matched, categories = [], []
            url = detail_url or source_url
            schedule = self._extract_schedule(text)
            cfg = settings()
            language = detect_regional_language(f"{title} {text}")
            raw_data = {
                "source": "live_portal",
                "source_url": source_url,
                "stable_url": (detail_url or source_url).split("?")[0],
                "detail_link_resolved": bool(detail_url),
                "scrape_method": scrape_method,
                "api_proxy_used": bool(cfg["use_proxy"] and cfg["scraper_api_key"] and scrape_method == "static_html"),
                "language": language,
                "original_language": language,
            }
            if language != "en":
                raw_data["regional_text_preserved"] = True
            if schedule["opening_date"]:
                raw_data["opening_date"] = schedule["opening_date"].isoformat()
            tender_id = self.generate_tender_id(title, url)
            if tender_id in seen:
                continue
            seen.add(tender_id)
            tenders.append(
                {
                    "tender_id": tender_id,
                    "title": title[:500],
                    "description": text,
                    "portal": self.portal_name,
                    "state": self.state,
                    "tender_url": url,
                    "published_date": schedule["published_date"],
                    "closing_date": schedule["closing_date"],
                    "estimated_value": self._parse_value(text),
                    "categories": categories,
                    "matched_keywords": matched,
                    "raw_data": raw_data,
                }
            )
        return tenders
