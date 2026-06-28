import asyncio
import hashlib
import json
import random
import re
from datetime import date, datetime, timedelta
from html import unescape
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

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
    "search by bid submission closing",
    "auction closing",
    "s.no e-published date",
    "organisation chain",
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
LISTING_FILTER_TITLES = {
    "closing today",
    "closing within 7 days",
    "closing within 14 days",
    "closing by date",
    "search by bid submission closing",
    "auction closing",
}
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
DOCUMENT_EXTENSIONS = (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".zip", ".rar", ".csv")
DETAIL_CONCURRENCY = 4


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

    # Utility methods used by portal scrapers.

    def _first_doc_value(self, doc: dict, *keys: str):
        """Return the first non-empty value from a Solr-style document dict."""
        for key in keys:
            value = doc.get(key)
            if isinstance(value, list):
                value = value[0] if value else None
            if value not in (None, "", [], {}):
                return value
        return None

    def _parse_iso_date(self, raw: str | None) -> date | None:
        """Parse ISO-8601 or epoch-ms date strings."""
        if not raw:
            return None
        raw = str(raw).strip()
        # epoch milliseconds
        if raw.isdigit() and len(raw) > 10:
            try:
                return datetime.utcfromtimestamp(int(raw) / 1000).date()
            except (ValueError, OSError):
                return None
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(raw[:19], fmt).date()
            except ValueError:
                continue
        return None

    def _parse_date_token(self, raw: str | None) -> date | None:
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

    def _parse_date(self, text: str, index: int = -1) -> date | None:
        matches = self._parse_all_dates(text)
        if not matches:
            return None
        return matches[index]

    def _labeled_date(self, text: str, labels: tuple[str, ...]) -> date | None:
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

    def _parse_value(self, text: str | None) -> float | None:
        if not text:
            return None
        match = VALUE_PATTERN.search(str(text))
        if not match:
            return None
        try:
            return float(match.group(1).replace(",", ""))
        except (ValueError, AttributeError):
            return None

    def _parse_month_day_time(self, month_str: str | None, day_str: str | None, time_str: str | None) -> date | None:
        """Parse Telangana-style split date values (month, day, time)."""
        if not month_str and not day_str:
            return None
        combined = " ".join(filter(None, [month_str, day_str, time_str, str(date.today().year)]))
        return self._parse_date_token(combined)

    def _is_likely_tender(self, title: str) -> bool:
        lowered = title.lower()
        if any(marker in lowered for marker in NON_TENDER_TITLE_MARKERS):
            return False
        return any(signal in lowered for signal in TENDER_SIGNALS)

    def _best_row_title(self, row) -> str:
        row_text = self.clean_text(row.get_text(" "))
        for match in BRACKET_PATTERN.findall(row_text):
            cleaned = self.clean_text(match)
            lowered = cleaned.lower()
            if len(cleaned) >= 12 and not DATE_PATTERN.search(cleaned) and lowered not in LISTING_FILTER_TITLES:
                return cleaned

        candidates: list[str] = []
        for cell in row.select("td, th"):
            text = self.clean_text(cell.get_text(" "))
            lowered = text.lower()
            if len(text) < 8:
                continue
            if lowered in NAV_TITLES or lowered in LISTING_FILTER_TITLES or any(marker in lowered for marker in FORM_OR_NAV_TEXT):
                continue
            if DATE_PATTERN.fullmatch(text) or re.fullmatch(r"\d{1,5}", text):
                continue
            candidates.append(text)
        tender_like = [item for item in candidates if self._is_likely_tender(item)]
        pool = tender_like or candidates
        if not pool:
            return ""
        return max(pool, key=len)

    def _is_tapestry_tender_listing(self, url: str, soup: BeautifulSoup) -> bool:
        lowered_url = (url or "").lower()
        if "frontendlisttendersbydate" not in lowered_url:
            return False
        page_text = self.clean_text(soup.get_text(" ")).lower()
        return "closing within 7 days" in page_text or "listtendersbydate" in page_text

    def _parse_candidates(
        self,
        soup: BeautifulSoup,
        source_url: str = "",
        scrape_method: str = "html_parse",
    ) -> list[dict]:
        """Generic HTML parser that extracts tender-like rows from any NIC/eProcurement page."""
        tenders: list[dict] = []
        seen: set[str] = set()

        # Try table rows first
        rows = soup.select("table tr")
        if not rows:
            rows = soup.select("tr")

        for row in rows:
            cells = row.select("td, th")
            if len(cells) < 2:
                continue
            anchors = row.select("a[href]")
            if not anchors:
                continue
            text = self.clean_text(row.get_text(" "))
            if len(text) < 10:
                continue
            lowered = text.lower()
            if any(nav in lowered for nav in FORM_OR_NAV_TEXT):
                continue

            detail_anchors = [
                anchor
                for anchor in anchors
                if any(
                    signal in " ".join(
                        str(part or "").lower()
                        for part in [anchor.get("href"), anchor.get("onclick"), anchor.get("title"), anchor.get_text(" ")]
                    )
                    for signal in DETAIL_LINK_SIGNALS
                )
            ]

            for anchor in detail_anchors or anchors:
                href = anchor.get("href", "")
                anchor_title = anchor.get("title") or self.clean_text(anchor.get_text(" "))
                title_raw = anchor_title
                if not title_raw or title_raw.lower() in NAV_TITLES or title_raw.lower() in GENERIC_TITLES or title_raw.lower() in LISTING_FILTER_TITLES:
                    title_raw = self._best_row_title(row)
                if not title_raw or title_raw.lower() in NAV_TITLES or title_raw.lower() in GENERIC_TITLES or title_raw.lower() in LISTING_FILTER_TITLES:
                    continue
                if len(title_raw) < 8 or any(marker in title_raw.lower() for marker in NON_TENDER_TITLE_MARKERS):
                    continue

                full_url = urljoin(source_url, href) if href and not href.lower().startswith(("javascript:", "#")) else source_url
                stable_url = full_url.split("?")[0]
                tender_text = f"{title_raw} {text} {href}"
                has_date = bool(DATE_PATTERN.search(text))
                has_detail_link = any(signal in (href or "").lower() for signal in DETAIL_LINK_SIGNALS)
                if not self._is_likely_tender(tender_text) or not (has_date or has_detail_link):
                    continue
                schedule = self._extract_schedule(text)
                tender_id = self.generate_tender_id(title_raw, str(schedule.get("closing_date") or ""))
                if tender_id in seen:
                    continue
                seen.add(tender_id)
                tenders.append({
                    "tender_id": tender_id,
                    "title": title_raw[:500],
                    "description": text[:1000],
                    "portal": self.portal_name,
                    "state": self.state,
                    "tender_url": full_url,
                    "published_date": schedule.get("published_date"),
                    "closing_date": schedule.get("closing_date"),
                    "estimated_value": self._parse_value(text),
                    "categories": [],
                    "matched_keywords": [],
                    "raw_data": {
                        "source": "live_portal",
                        "source_url": source_url,
                        "stable_url": stable_url,
                        "scrape_method": scrape_method,
                        "opening_date": schedule.get("opening_date").isoformat() if schedule.get("opening_date") else None,
                    },
                })
        return tenders

    async def _enrich_missing_schedule(self, tenders: list[dict]) -> None:
        """Fetch detail pages for tenders missing closing_date, up to DETAIL_ENRICHMENT_LIMIT."""
        missing = [t for t in tenders if not t.get("closing_date")][:DETAIL_ENRICHMENT_LIMIT]
        for tender in missing:
            detail_url = tender.get("tender_url") or ""
            if not detail_url or not any(signal in detail_url.lower() for signal in DETAIL_LINK_SIGNALS):
                continue
            try:
                detail_soup = await self.fetch_static(detail_url)
                detail_text = self.clean_text(detail_soup.get_text(" "))
                schedule = self._extract_schedule(detail_text)
                for key in ("published_date", "closing_date"):
                    if schedule.get(key) and not tender.get(key):
                        tender[key] = schedule[key]
                if schedule.get("opening_date"):
                    raw = dict(tender.get("raw_data") or {})
                    raw["opening_date"] = schedule["opening_date"].isoformat()
                    tender["raw_data"] = raw
            except Exception:
                pass

    def _extract_document_links(self, soup: BeautifulSoup, source_url: str) -> list[str]:
        urls: list[str] = []
        for anchor in soup.select("a[href]"):
            href = self.clean_text(anchor.get("href"))
            if not href or href.lower().startswith(("javascript:", "#", "mailto:", "tel:")):
                continue
            text = self.clean_text(anchor.get_text(" ")).lower()
            absolute = urljoin(source_url, href)
            lowered = absolute.lower().split("?", 1)[0]
            if lowered.endswith(DOCUMENT_EXTENSIONS) or any(
                marker in text
                for marker in (
                    "download",
                    "boq",
                    "nit",
                    "document",
                    "corrigendum",
                    "specification",
                    "bid document",
                    "tender document",
                )
            ):
                urls.append(absolute)
        return list(dict.fromkeys(urls))

    def _labeled_text_value(self, text: str, labels: tuple[str, ...], max_chars: int = 160) -> str | None:
        for label in labels:
            pattern = re.compile(rf"{re.escape(label)}\s*[:\-]?\s*(?P<value>.{{2,{max_chars}}})", re.IGNORECASE)
            match = pattern.search(text)
            if match:
                value = self.clean_text(match.group("value"))
                value = re.split(r"\s{2,}|(?:\b[A-Z][A-Za-z /]{2,30}\s*[:\-])", value)[0]
                if value:
                    return value[:max_chars]
        return None

    def _extract_detail_metadata(self, soup: BeautifulSoup, source_url: str) -> dict[str, Any]:
        text = self.clean_text(soup.get_text(" "))
        schedule = self._extract_schedule(text)
        lowered = text.lower()
        status = "ACTIVE"
        if "cancelled" in lowered or "canceled" in lowered:
            status = "CANCELLED"
        elif "retender" in lowered:
            status = "RETENDERED"
        elif "corrigendum" in lowered:
            status = "CORRIGENDUM"

        value = self._parse_value(text)
        return {
            "published_date": schedule.get("published_date"),
            "closing_date": schedule.get("closing_date"),
            "opening_date": schedule.get("opening_date"),
            "estimated_value": value,
            "tender_status": status,
            "corrigendum": "corrigendum" in lowered,
            "department": self._labeled_text_value(text, ("Department", "Dept", "Organisation", "Organization", "Ministry")),
            "buyer": self._labeled_text_value(text, ("Buyer", "Purchaser", "Officer", "Contact Person")),
            "organization": self._labeled_text_value(text, ("Organisation Chain", "Organization Chain", "Organisation", "Organization")),
            "location": self._labeled_text_value(text, ("Location", "Place of Work", "Work Location", "District")),
            "reference_number": self._labeled_text_value(text, ("Tender Reference Number", "Tender Ref No", "Reference No", "Ref No")),
            "bid_number": self._labeled_text_value(text, ("Bid Number", "Bid No", "Tender ID", "NIT")),
            "detail_text": text[:5000],
            "document_urls": self._extract_document_links(soup, source_url),
        }

    async def _fetch_detail_soup(self, detail_url: str, client: httpx.AsyncClient | None = None) -> BeautifulSoup:
        if client:
            response = await client.get(detail_url, headers=self._session_headers(detail_url))
            response.raise_for_status()
            return BeautifulSoup(response.text, "html.parser")
        return await self.fetch_static(detail_url)

    async def _enrich_one_detail(self, tender: dict, client: httpx.AsyncClient | None = None) -> None:
        detail_url = tender.get("tender_url") or ""
        source_url = (tender.get("raw_data") or {}).get("source_url")
        if not detail_url or detail_url == source_url:
            return
        if not any(signal in detail_url.lower() for signal in DETAIL_LINK_SIGNALS):
            return
        raw_data = dict(tender.get("raw_data") or {})
        try:
            detail_soup = await self._fetch_detail_soup(detail_url, client=client)
            metadata = self._extract_detail_metadata(detail_soup, detail_url)
        except Exception as exc:
            raw_data["detail_enrichment_status"] = "failed"
            raw_data["detail_enrichment_error"] = str(exc)[:240]
            tender["raw_data"] = raw_data
            return

        for field in ("published_date", "closing_date", "estimated_value", "tender_status"):
            if metadata.get(field) not in (None, "", []):
                tender[field] = metadata[field]
        for field in ("department", "buyer", "organization", "location", "reference_number", "bid_number"):
            if metadata.get(field):
                tender[field] = tender.get(field) or metadata[field]
                raw_data[field] = raw_data.get(field) or metadata[field]
        if metadata.get("opening_date"):
            raw_data["opening_date"] = metadata["opening_date"].isoformat()
        if metadata.get("corrigendum"):
            tender["corrigendum"] = True
            raw_data["corrigendum_detected"] = True
        if metadata.get("detail_text"):
            raw_data["detail_text"] = metadata["detail_text"]
        if metadata.get("document_urls"):
            existing = raw_data.get("document_urls") or []
            raw_data["document_urls"] = list(dict.fromkeys([*existing, *metadata["document_urls"]]))
        raw_data["detail_enrichment_status"] = "checked"
        tender["raw_data"] = raw_data

    async def enrich_detail_pages(self, tenders: list[dict], client: httpx.AsyncClient | None = None) -> None:
        semaphore = asyncio.Semaphore(DETAIL_CONCURRENCY)

        async def run_one(tender: dict) -> None:
            async with semaphore:
                await self._enrich_one_detail(tender, client=client)

        await asyncio.gather(*(run_one(tender) for tender in tenders), return_exceptions=True)

    async def _fetch_nprocure_closing_report(self, client, report_url: str, date_str: str) -> BeautifulSoup:
        """Fetch nProcure bid-closing report for a given date."""
        headers = {
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "text/html,*/*",
            "Referer": report_url,
        }
        response = await client.post(
            report_url,
            data={"bidSubmissionClosingDate": date_str, "tenderType": ""},
            headers=headers,
        )
        response.raise_for_status()
        return BeautifulSoup(response.text, "html.parser")

    def _parse_nprocure_closing_report(
        self, soup: BeautifulSoup, source_url: str, stable_url: str, closing_day: date
    ) -> list[dict]:
        """Parse nProcure closing report table into tender records."""
        tenders = []
        seen: set[str] = set()
        for row in soup.select("table tr"):
            cells = row.select("td")
            if len(cells) < 3:
                continue
            cell_texts = [self.clean_text(c.get_text(" ")) for c in cells]
            tender_number = cell_texts[0] if cell_texts else ""
            title_text = cell_texts[1] if len(cell_texts) > 1 else tender_number
            if not tender_number or not title_text or len(title_text) < 4:
                continue
            anchor = row.select_one("a[href]")
            detail_url = urljoin(source_url, anchor["href"]) if anchor else source_url
            tender_id = self.generate_tender_id(tender_number, str(closing_day))
            if tender_id in seen:
                continue
            seen.add(tender_id)
            title = f"{tender_number} - {title_text}"
            tenders.append({
                "tender_id": tender_id,
                "title": title[:500],
                "description": " ".join(cell_texts),
                "portal": self.portal_name,
                "state": self.state,
                "tender_url": detail_url,
                "published_date": None,
                "closing_date": closing_day,
                "estimated_value": self._parse_value(" ".join(cell_texts)),
                "categories": [],
                "matched_keywords": [],
                "raw_data": {
                    "source": "live_portal",
                    "source_url": source_url,
                    "stable_url": stable_url,
                    "scrape_method": "nprocure_closing_report",
                    "tender_number": tender_number,
                },
            })
        return tenders

    # HTTP fetch methods.

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

    def _session_headers(self, referer: str | None = None) -> dict[str, str]:
        return {
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-IN,en;q=0.9",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "Referer": referer or self.base_url,
        }

    def _collect_form_data(self, form) -> dict[str, str]:
        data: dict[str, str] = {}
        for field in form.select("input, select, textarea"):
            name = field.get("name")
            if not name:
                continue
            if field.name == "select":
                selected = field.select_one("option[selected]") or field.select_one("option")
                data[name] = selected.get("value", "") if selected else ""
            elif field.name == "textarea":
                data[name] = field.get_text()
            elif field.get("type", "").lower() in {"checkbox", "radio"}:
                if field.has_attr("checked"):
                    data[name] = field.get("value", "on")
            else:
                data[name] = field.get("value", "")
        return data

    def _find_tapestry_form(self, soup: BeautifulSoup, url: str):
        for candidate in soup.select("form"):
            inputs_text = " ".join(
                f"{field.get('name') or ''}={field.get('value') or ''}".lower()
                for field in candidate.select("input")
            ).lower()
            if any(marker in inputs_text for marker in ("listtendersbydate", "linksubmit", "submitname", "submitmode", "t:formdata")):
                return candidate
        forms = soup.select("form")
        if forms:
            return forms[0]
        raise RuntimeError(f"No Tapestry form found on {url}")

    def _next_tapestry_link_submit(self, soup: BeautifulSoup, current_page_index: int) -> str | None:
        """Find the next LinkSubmit_* token from pager links/buttons on NIC Tapestry pages."""
        current = f"linksubmit_{current_page_index}".lower()
        candidates: list[tuple[int, str]] = []
        for element in soup.select("a[href], input[name], button[name]"):
            blob = " ".join(
                str(part or "")
                for part in [
                    element.get("href"),
                    element.get("onclick"),
                    element.get("name"),
                    element.get("id"),
                    element.get("value"),
                    element.get_text(" "),
                ]
            )
            for match in re.finditer(r"LinkSubmit_(\d+)", blob, re.IGNORECASE):
                token = f"LinkSubmit_{match.group(1)}"
                index = int(match.group(1))
                if token.lower() != current and index >= current_page_index:
                    candidates.append((index, token))
        if not candidates:
            return None
        candidates.sort(key=lambda item: (item[0] <= current_page_index, item[0]))
        return candidates[0][1]

    def _strip_session_bound_query(self, url: str) -> str:
        parsed = urlparse(url)
        query = [
            (key, value)
            for key, value in parse_qsl(parsed.query, keep_blank_values=True)
            if key.lower() not in {"session", "sp", "jsessionid"}
        ]
        return urlunparse(parsed._replace(query=urlencode(query, doseq=True)))

    async def fetch_tapestry_submit_with_client(
        self,
        client: httpx.AsyncClient,
        url: str,
        submit_name: str = "LinkSubmit_0",
        current_soup: BeautifulSoup | None = None,
        current_url: str | None = None,
    ) -> BeautifulSoup:
        """
        Submit a NIC/Apache Tapestry listing form with the caller-owned client.
        Keeping one client for all pages preserves JSESSIONID/Tapestry cookies.
        """
        headers = self._session_headers(current_url or url)
        if current_soup is None:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            current_soup = BeautifulSoup(response.text, "html.parser")
            current_url = str(response.url)

        form = self._find_tapestry_form(current_soup, current_url or url)
        data = self._collect_form_data(form)
        data["submitname"] = submit_name
        data.setdefault("submitmode", "")
        if "t:submit" in data:
            data["t:submit"] = f'["{submit_name}","{submit_name}"]'
        action = urljoin(current_url or url, form.get("action") or current_url or url)
        submitted = await client.post(
            action,
            data=data,
            headers={
                **headers,
                "Referer": current_url or url,
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        submitted.raise_for_status()
        return BeautifulSoup(submitted.text, "html.parser")

    async def fetch_tapestry_submit(self, url: str, submit_name: str = "LinkSubmit_0") -> BeautifulSoup:
        """
        Submit one NIC/Apache Tapestry listing form using a fresh session.
        Prefer scrape_tapestry_listing_pages() when walking multiple pages.
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
            return await self.fetch_tapestry_submit_with_client(client, url, submit_name)

    async def scrape_tapestry_listing_pages(self, url: str, search_query: str | None = None) -> list[dict]:
        """Walk all reachable NIC/Apache Tapestry listing pages in one session."""
        cfg = settings()
        tenders: list[dict] = []
        seen: set[str] = set()
        empty_or_duplicate_pages = 0
        headers = self._session_headers(url)
        async with httpx.AsyncClient(
            timeout=cfg["scraper_request_timeout_seconds"],
            follow_redirects=True,
            headers=headers,
            verify=False,
        ) as client:
            current_url = url
            current_soup: BeautifulSoup | None = None
            submit_name = "LinkSubmit_0"
            used_submit_names: set[str] = set()

            for page_index in range(cfg["max_pages_per_portal"]):
                if submit_name in used_submit_names:
                    break
                used_submit_names.add(submit_name)
                try:
                    soup = await self.fetch_tapestry_submit_with_client(
                        client,
                        url,
                        submit_name=submit_name,
                        current_soup=current_soup,
                        current_url=current_url,
                    )
                    current_soup = soup
                    parsed = self._parse_candidates(
                        soup,
                        source_url=url,
                        scrape_method=f"nic_tapestry_session_{submit_name}",
                    )
                    await self.enrich_detail_pages(parsed, client=client)
                except Exception as exc:
                    print(f"{self.portal_name} Tapestry {submit_name} failed: {exc}")
                    if page_index == 0:
                        break
                    break

                new_on_page = 0
                for tender in parsed:
                    if search_query:
                        text_to_search = f"{tender.get('title', '')} {tender.get('description', '')}".lower()
                        if search_query.lower() not in text_to_search:
                            continue

                    raw_data = dict(tender.get("raw_data") or {})
                    raw_data["stable_url"] = self._strip_session_bound_query(
                        raw_data.get("stable_url") or tender.get("tender_url") or url
                    )
                    raw_data["source_url"] = raw_data.get("source_url") or url
                    raw_data["page_number"] = page_index + 1
                    raw_data["session_scope"] = "single_portal_listing"
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

                next_submit_name = self._next_tapestry_link_submit(soup, page_index)
                submit_name = next_submit_name or f"LinkSubmit_{page_index + 1}"
                await asyncio.sleep(0.2)
        return tenders

    async def fetch_dynamic(self, url: str) -> BeautifulSoup:
        from scrapers.browser_pool import BROWSER_POOL

        def run_selenium(target_url: str) -> str:
            proxy = None
            if settings().get("use_proxy") and settings().get("scraper_proxy_list"):
                proxy = random.choice(settings().get("scraper_proxy_list").split(","))
            driver = BROWSER_POOL.acquire_selenium_driver(proxy_server=proxy)
            try:
                driver.get(target_url)
                import time
                time.sleep(2)
                return driver.page_source
            finally:
                driver.quit()

        try:
            page, release_callback, idx = await BROWSER_POOL.acquire_page()
            try:
                await page.goto(url, wait_until="networkidle", timeout=settings()["scraper_request_timeout_seconds"] * 1000)
                html = await page.content()
                return BeautifulSoup(html, "html.parser")
            except Exception:
                await release_callback()
                await BROWSER_POOL.restart_browser(idx)
                page, release_callback, idx = await BROWSER_POOL.acquire_page()
                try:
                    await page.goto(url, wait_until="networkidle", timeout=settings()["scraper_request_timeout_seconds"] * 1000)
                    html = await page.content()
                    return BeautifulSoup(html, "html.parser")
                finally:
                    await release_callback()
            else:
                await release_callback()

        except Exception as exc:
            print(f"Playwright failed for {url}: {exc}. Trying Selenium fallback...")
            try:
                html = await asyncio.to_thread(run_selenium, url)
                return BeautifulSoup(html, "html.parser")
            except Exception as sel_exc:
                raise RuntimeError(f"dynamic browser scrape failed under both Playwright and Selenium. Playwright: {exc}, Selenium: {sel_exc}")


    async def soup(self, url: str) -> BeautifulSoup:
        use_browser = self.use_playwright and settings()["use_playwright"]
        return await (self.fetch_dynamic(url) if use_browser else self.fetch_static(url))

    # Core scrape interface.

    async def scrape(self, search_query: str | None = None) -> list[dict]:
        raise NotImplementedError

    async def scrape_all(self) -> list[dict]:
        """Alias called by the registry. Delegates to scrape()."""
        return await self.scrape()
