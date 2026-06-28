import asyncio
import random
from typing import Any
from playwright.async_api import async_playwright

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Edge/120.0.0.0 Safari/537.36",
]

class BrowserPool:
    def __init__(self, pool_size: int = 3):
        self._pool_size = pool_size
        self._browsers: list = []
        self._contexts: list = []
        self._semaphore: asyncio.Semaphore | None = None
        self._playwright = None
        self._lock = asyncio.Lock()
        self._initialized = False
        self._round_robin_idx = 0

    async def initialize(self) -> None:
        async with self._lock:
            if self._initialized:
                return
            
            self._playwright = await async_playwright().start()
            self._semaphore = asyncio.Semaphore(self._pool_size)
            
            for _ in range(self._pool_size):
                await self._launch_browser_context()
                
            self._initialized = True

    async def _launch_browser_context(self):
        headless_val = settings().get("headless_mode", True)
        browser = await self._playwright.chromium.launch(headless=headless_val)
        context = await browser.new_context(
            user_agent=random.choice(USER_AGENTS),
            viewport={"width": 1280, "height": 900},
            ignore_https_errors=True
        )
        self._browsers.append(browser)
        self._contexts.append(context)

    async def acquire_page(self) -> tuple[Any, Any, int]:
        if not self._initialized:
            await self.initialize()
            
        await self._semaphore.acquire()
        
        async with self._lock:
            idx = self._round_robin_idx
            self._round_robin_idx = (self._round_robin_idx + 1) % self._pool_size
            context = self._contexts[idx]
            
        page = await context.new_page()
        
        async def release_callback():
            await self.release_page(page)
            
        return page, release_callback, idx

    async def release_page(self, page) -> None:
        try:
            if not page.is_closed():
                await page.close()
        except Exception:
            pass
        finally:
            self._semaphore.release()

    async def close(self) -> None:
        async with self._lock:
            if not self._initialized:
                return
            for context in self._contexts:
                try:
                    await context.close()
                except Exception:
                    pass
            for browser in self._browsers:
                try:
                    await browser.close()
                except Exception:
                    pass
            if self._playwright:
                try:
                    await self._playwright.stop()
                except Exception:
                    pass
            self._browsers.clear()
            self._contexts.clear()
            self._initialized = False

    async def restart_browser(self, index: int) -> None:
        async with self._lock:
            if index >= len(self._browsers):
                return
            try:
                await self._contexts[index].close()
                await self._browsers[index].close()
            except Exception:
                pass
            
            headless_val = settings().get("headless_mode", True)
            browser = await self._playwright.chromium.launch(headless=headless_val)
            context = await browser.new_context(
                user_agent=random.choice(USER_AGENTS),
                viewport={"width": 1280, "height": 900},
                ignore_https_errors=True
            )
            self._browsers[index] = browser
            self._contexts[index] = context

    def acquire_selenium_driver(self, proxy_server: str | None = None) -> Any:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        
        options = Options()
        headless_val = settings().get("headless_mode", True)
        if headless_val:
            options.add_argument("--headless=new")
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument(f"user-agent={random.choice(USER_AGENTS)}")
        options.add_argument("--ignore-certificate-errors")
        
        if proxy_server:
            options.add_argument(f"--proxy-server={proxy_server}")
            
        driver = webdriver.Chrome(options=options)
        driver.set_page_load_timeout(settings().get("scraper_request_timeout_seconds", 30))
        return driver

from app.config import settings
BROWSER_POOL = BrowserPool(pool_size=settings().get("browser_pool_size", 3))

