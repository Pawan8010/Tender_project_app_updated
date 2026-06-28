import sys

file_path = r"c:\Users\rajpu\Downloads\1233\backend\scrapers\base_scraper.py"

with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# I need to restore the fetch_tapestry_submit function completely, fetch_dynamic completely, and soup completely.
# Let's find the start of fetch_tapestry_submit
start_idx = content.find("    async def fetch_tapestry_submit(self, url: str, submit_name: str = \"LinkSubmit_0\") -> BeautifulSoup:")
if start_idx == -1:
    print("Cannot find fetch_tapestry_submit")
    sys.exit(1)

# Let's find the start of GenericTenderScraper
end_idx = content.find("class GenericTenderScraper(BaseScraper):")
if end_idx == -1:
    print("Cannot find GenericTenderScraper")
    sys.exit(1)

proper_code = """    async def fetch_tapestry_submit(self, url: str, submit_name: str = "LinkSubmit_0") -> BeautifulSoup:
        \"\"\"
        Submit a NIC/Apache Tapestry tender listing form while preserving the
        fresh session cookie from the first page load.
        \"\"\"
        import random
        from urllib.parse import urljoin
        import httpx
        from bs4 import BeautifulSoup
        from app.config import settings
        
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
        from bs4 import BeautifulSoup
        from app.config import settings
        from scrapers.browser_pool import BROWSER_POOL
        
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
            raise RuntimeError(f"dynamic browser scrape failed: {exc}") from exc

    async def soup(self, url: str) -> BeautifulSoup:
        from app.config import settings
        use_browser = self.use_playwright and settings()["use_playwright"]
        return await (self.fetch_dynamic(url) if use_browser else self.fetch_static(url))

    async def scrape(self) -> list[dict]:
        raise NotImplementedError

"""

new_content = content[:start_idx] + proper_code + content[end_idx:]

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(new_content)

print("base_scraper.py repaired successfully")
