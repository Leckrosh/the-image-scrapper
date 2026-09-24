"""
Bing Images source: Works for headless browser. September 24, 2026.

Because Bing do not requires a CAPTCHA, it actually works with a headless browser.

NOTES:

- Each result tile is an <a class="iusc"> whose `m` attribute is a JSON blob:
      murl -> full-resolution origin URL (Any other like turl, is not required)
- I tried https://www.bing.com/images/search?q=ferrari+italia&first=1, and by modifying more the "first" parameter in the request
  the idea was to get more results, but it didn't works, because of that it ends up requiring a scroll.

  
Please, if harvesting returns nothing, report it as an issue to update the method.
"""

from __future__ import annotations

import sys
import time
from collections.abc import Iterator
from urllib.parse import quote_plus

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from ..models import ImageResult
from .base import USER_AGENT, ImageSource

# FRAGILE ZONE - Bing markup/URL. If harvesting returns nothing, this is the most probable section that needs to be updated.
IMAGES_SEARCH_URL = "https://www.bing.com/images/search"
IUSC_SELECTOR = "a.iusc"
SEEMORE_SELECTOR = "a.btn_seemore, .btn_seemore"
_EXTRACT_JS = (
    "els => els.map(a => { try { const m = JSON.parse(a.getAttribute('m')); "
    "return {murl: m.murl || null, turl: m.turl || null, purl: m.purl || null}; } "
    "catch (e) { return null; } }).filter(x => x && x.murl)"
)

_SAFE_SEARCH = {"strict": "STRICT", "moderate": "DEMOTE", "off": "OFF"}

_LAUNCH_ARGS = ["--disable-blink-features=AutomationControlled"]
_IGNORE_DEFAULT_ARGS = ["--enable-automation"]


def _log(message: str) -> None:
    print(f"[imagegrab] {message}", file=sys.stderr)


class BingImagesSource(ImageSource):

    name = "bing"

    def __init__(
        self,
        headful: bool = False,
        pace: float = 1.0,
        safe_search: str = "off",
        nav_timeout_ms: int = 30_000,
        max_stagnant_rounds: int = 4,
    ) -> None:
        self.headful = headful
        self.pace = pace
        self.safe_search = safe_search
        self.nav_timeout_ms = nav_timeout_ms
        self.max_stagnant_rounds = max_stagnant_rounds

    def search(self, query: str, limit: int) -> Iterator[ImageResult]:
        level = _SAFE_SEARCH.get(self.safe_search.lower(), "OFF")
        url = (
            f"{IMAGES_SEARCH_URL}?q={quote_plus(query)}"
            f"&safeSearch={level.lower()}"
        )
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
            context.add_cookies(
                [
                    {
                        "name": "SRCHHPGUSR",
                        "value": f"ADLT={level}",
                        "domain": ".bing.com",
                        "path": "/",
                    }
                ]
            )
            page = context.new_page()
            page.set_default_timeout(self.nav_timeout_ms)
            try:
                page.goto(url, wait_until="domcontentloaded")
                try:
                    page.wait_for_selector(
                        IUSC_SELECTOR, timeout=self.nav_timeout_ms
                    )
                except PlaywrightTimeoutError:
                    _log(
                        "Bing returned no image tiles - the markup may have "
                        "changed (update selectors in sources/bing.py)."
                    )
                    return
                yield from self._harvest(page, query, limit)
            finally:
                context.close()
                browser.close()

    def _harvest(self, page, query: str, limit: int) -> Iterator[ImageResult]:
        seen: set[str] = set()
        stagnant_rounds = 0

        while len(seen) < limit and stagnant_rounds < self.max_stagnant_rounds:
            tiles = page.eval_on_selector_all(IUSC_SELECTOR, _EXTRACT_JS)
            new_this_round = 0
            for tile in tiles:
                murl = tile.get("murl")
                if not murl or murl in seen:
                    continue
                seen.add(murl)
                new_this_round += 1
                yield ImageResult(
                    image_url=murl,
                    query=query,
                    source=self.name,
                    thumbnail_url=tile.get("turl"),
                    source_page=tile.get("purl"),
                )
                if len(seen) >= limit:
                    break

            if len(seen) >= limit:
                break

            grew = self._scroll(page, len(tiles))
            stagnant_rounds = 0 if (new_this_round or grew) else stagnant_rounds + 1
            if self.pace:
                time.sleep(self.pace)

    def _scroll(self, page, prev_tile_count: int) -> bool:
        page.mouse.wheel(0, 20_000)
        page.wait_for_timeout(1_200)
        try:
            button = page.query_selector(SEEMORE_SELECTOR)
            if button and button.is_visible():
                button.click()
                page.wait_for_timeout(1_200)
        except Exception:
            pass
        return len(page.query_selector_all(IUSC_SELECTOR)) > prev_tile_count
