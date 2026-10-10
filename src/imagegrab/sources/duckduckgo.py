"""
DuckDuckGo Images source: Works ONLY with a headful browser, so it always runs headful (no flag needed). September 27, 2026.

DuckDuckGo refuses headless browsers: the very first request is redirected to its error page
(`static-pages/home-error/418.html`, "Unexpected error"). Headful didn't ask for a CAPTCHA.

NOTES:

- DDG serves Bing's image index, so the overlap is extreme with Bing and Yahoo, however, it still gives 
  around 50-100 unique images, anyway, if you want to make multiple sources download, DDG could be used before Bing & Yahoo..
- DuckDuckGo stops around 250-375 images per term, I didn't figure it out how to reach more results.
- SafeSearch is turned off with `&kp=-2` in the URL and apparently this '&kbj=1' works for discard AI images.

Please, if harvesting returns nothing, report it as an issue to update the method.
"""

from __future__ import annotations

import sys
import time
from collections.abc import Iterator
from urllib.parse import quote_plus, urlparse

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

from ..models import ImageResult
from .base import USER_AGENT, ImageSource

# FRAGILE ZONE - DuckDuckGo URL/endpoint. If harvesting returns nothing, this is the most probable section that needs to be updated.
IMAGES_SEARCH_URL = "https://duckduckgo.com/"
RESULTS_HOST = "duckduckgo.com"
RESULTS_PATH = "/i.js"
ERROR_PAGE_MARKER = "/static-pages/home-error/"
SCROLL_PX = 20_000
RESPONSE_WAIT_MS = 3_000

_SAFE_SEARCH = {"strict": "1", "moderate": "-1", "off": "-2"}

_LAUNCH_ARGS = ["--disable-blink-features=AutomationControlled"]
_IGNORE_DEFAULT_ARGS = ["--enable-automation"]


def _log(message: str) -> None:
    print(f"[tis] {message}", file=sys.stderr)


def _is_results(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.hostname == RESULTS_HOST and parsed.path == RESULTS_PATH


class DuckDuckGoImagesSource(ImageSource):

    name = "duckduckgo"
    headless = False

    def __init__(
        self,
        headful: bool = False,
        pace: float = 1.0,
        safe_search: str = "off",
        hide_ai_images: bool = False,
        nav_timeout_ms: int = 30_000,
        max_stagnant_rounds: int = 3,
    ) -> None:
        self.headful = headful
        self.pace = pace
        self.safe_search = safe_search
        self.hide_ai_images = hide_ai_images
        self.nav_timeout_ms = nav_timeout_ms
        self.max_stagnant_rounds = max_stagnant_rounds

    def search(self, query: str, limit: int) -> Iterator[ImageResult]:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=not self.headful,
                args=_LAUNCH_ARGS,
                ignore_default_args=_IGNORE_DEFAULT_ARGS,
            )
            context = browser.new_context(
                user_agent=USER_AGENT,
                locale="en-US",
                viewport={"width": 1366, "height": 900},
            )
            page = context.new_page()
            page.set_default_timeout(self.nav_timeout_ms)

            responses: list = []

            def capture(response) -> None:
                if _is_results(response.url):
                    responses.append(response)

            page.on("response", capture)
            try:
                if self._open_results(page, query, responses):
                    yield from self._harvest(page, query, limit, responses)
            finally:
                context.close()
                browser.close()

    def _open_results(self, page, query: str, responses: list) -> bool:
        kp = _SAFE_SEARCH.get(self.safe_search.lower(), "-2")
        url = f"{IMAGES_SEARCH_URL}?q={quote_plus(query)}&iax=images&ia=images&kp={kp}"
        if self.hide_ai_images:
            url += "&kbj=1"
        page.goto(url, wait_until="domcontentloaded")
        if ERROR_PAGE_MARKER in page.url:
            if self.headful:
                _log(
                    "DuckDuckGo answered with its error page instead of the results. "
                    "Wait a few minutes and try again."
                )
            else:
                _log(
                    "DuckDuckGo refuses headless browsers (it answered with its error "
                    "page). Re-run with --headful."
                )
            return False
        if not self._wait_for_responses(page, responses, self.nav_timeout_ms):
            _log(
                "DuckDuckGo returned no image results - the page may have changed "
                "(update the FRAGILE ZONE in sources/duckduckgo.py)."
            )
            return False
        return True

    def _harvest(
        self, page, query: str, limit: int, responses: list
    ) -> Iterator[ImageResult]:
        seen: set[str] = set()
        stagnant_rounds = 0

        while True:
            new_this_round = 0
            exhausted = False
            while responses:
                payload = self._payload(responses.pop(0))
                if payload is None:
                    return
                for item in payload.get("results") or []:
                    murl = item.get("image")
                    if not murl or murl in seen:
                        continue
                    seen.add(murl)
                    new_this_round += 1
                    yield ImageResult(
                        image_url=murl,
                        query=query,
                        source=self.name,
                        thumbnail_url=item.get("thumbnail"),
                        source_page=item.get("url"),
                    )
                    if len(seen) >= limit:
                        return
                if not payload.get("next"):
                    exhausted = True

            if exhausted:
                _log(f"DuckDuckGo has no more results for this term ({len(seen)} found).")
                return
            stagnant_rounds = 0 if new_this_round else stagnant_rounds + 1
            if stagnant_rounds >= self.max_stagnant_rounds:
                _log(f"DuckDuckGo stopped loading more results ({len(seen)} found).")
                return

            page.mouse.wheel(0, SCROLL_PX)
            self._wait_for_responses(page, responses, RESPONSE_WAIT_MS)
            if self.pace:
                time.sleep(self.pace)

    def _payload(self, response) -> dict | None:
        if response.status != 200:
            _log(
                f"DuckDuckGo refused a results request (HTTP {response.status}) - it "
                "may be rate-limiting. Wait a few minutes and try again."
            )
            return None
        try:
            payload = response.json()
        except (PlaywrightError, ValueError):
            payload = None
        if not isinstance(payload, dict):
            _log(
                "DuckDuckGo sent results that couldn't be read - the format may have "
                "changed (update the FRAGILE ZONE in sources/duckduckgo.py)."
            )
            return None
        return payload

    def _wait_for_responses(self, page, responses: list, timeout_ms: int) -> bool:
        deadline = time.monotonic() + timeout_ms / 1000
        while not responses:
            if time.monotonic() > deadline:
                return False
            page.wait_for_timeout(250)
        return True
