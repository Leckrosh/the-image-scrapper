"""
Yahoo Images source: Works for headless browser (and headful). September 27, 2026.

Yahoo didn't ask for a CAPTCHA. However, it does get 500 response in Headless Chrome.

NOTES:

- According to research, Yahoo serves Bing's image index but it don't fully overlap, so it worths to add it.
- Scrolling loads more results through the same URL, so instead of scrolling, pages are requested with `&b=N`
  (1-based offset, up to 60 images per page). Each page embeds `"nextOffset":"N"`, where the next page starts.
- For some reason, Yahoo stops at a few hundred results per term (~350-500). Once the limit is reached, yahoo will no
  longer give further results. In the plan is being considered a json for the settings of each browser. I'll keep that in mind
  in order to automatically having the limit set per browser because insisting on harvesting won't work at all.
- It didn't show up in testing, but Yahoo might send to a consent page. In case Yahoo triggers something like that (CAPTCHA,
  consent page, etc), the behaviour is like in chrome, it will wait for human intervention to authorize or do the CAPTCHA.
  With --unattended it never waits: the run stops and reports that human intervention was required.

Please, if harvesting returns nothing, report it as an issue to update the method.
"""

from __future__ import annotations

import sys
import time
from collections.abc import Iterator
from urllib.parse import quote_plus, urlparse

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from ..models import ImageResult
from .base import USER_AGENT, HumanInterventionRequired, ImageSource

# Please, if you need more time to accept a consent page, modify it here.
SOLVE_TIMEOUT_MS = 180_000

# FRAGILE ZONE - Yahoo markup/URL. If harvesting returns nothing, this is the most probable section that needs to be updated.
IMAGES_SEARCH_URL = "https://images.search.yahoo.com/search/images"
RESULTS_HOST = "images.search.yahoo.com"
TILE_SELECTOR = "a[data-origurl]"
PAGE_SIZE = 60
MAX_PAGES = 20
_EXTRACT_JS = r"""
els => els.map(a => {
  const img = a.querySelector('img');
  return {murl: a.getAttribute('data-origurl'), turl: img ? img.getAttribute('src') : null,
          purl: a.getAttribute('data-referenceurl')};
}).filter(x => x.murl)
"""
_NEXT_OFFSET_JS = r"""
() => {
  for (const s of document.scripts) {
    const m = /"nextOffset":"(\d+)"/.exec(s.textContent);
    if (m) return Number(m[1]);
  }
  return null;
}
"""

_SAFE_SEARCH = {"strict": "r", "moderate": "r", "off": "p"}

_LAUNCH_ARGS = ["--disable-blink-features=AutomationControlled"]
_IGNORE_DEFAULT_ARGS = ["--enable-automation"]


def _log(message: str) -> None:
    print(f"[tis] {message}", file=sys.stderr)


class YahooImagesSource(ImageSource):

    name = "yahoo"

    def __init__(
        self,
        headful: bool = False,
        pace: float = 1.0,
        safe_search: str = "off",
        unattended: bool = False,
        nav_timeout_ms: int = 30_000,
        solve_timeout_ms: int = SOLVE_TIMEOUT_MS,
        max_stagnant_rounds: int = 2,
    ) -> None:
        self.headful = headful
        self.pace = pace
        self.safe_search = safe_search
        self.unattended = unattended
        self.nav_timeout_ms = nav_timeout_ms
        self.solve_timeout_ms = solve_timeout_ms
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
            try:
                yield from self._harvest(page, query, limit)
            finally:
                context.close()
                browser.close()

    def _harvest(self, page, query: str, limit: int) -> Iterator[ImageResult]:
        seen: set[str] = set()
        stagnant_rounds = 0
        offset = 0

        for _ in range(MAX_PAGES):
            loaded = self._load_page(page, query, offset)
            if loaded is None:
                return
            tiles, next_offset = loaded

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
                    return

            if next_offset is None:
                next_offset = offset + PAGE_SIZE
            if next_offset <= offset:
                _log(f"Yahoo has no more results for this term ({len(seen)} found).")
                return
            offset = next_offset
            stagnant_rounds = 0 if new_this_round else stagnant_rounds + 1
            if stagnant_rounds >= self.max_stagnant_rounds:
                return
            if self.pace:
                time.sleep(self.pace)

    def _load_page(self, page, query: str, offset: int) -> tuple[list[dict], int | None] | None:
        vm = _SAFE_SEARCH.get(self.safe_search.lower(), "p")
        url = f"{IMAGES_SEARCH_URL}?p={quote_plus(query)}&vm={vm}&b={offset + 1}"
        response = page.goto(url, wait_until="domcontentloaded")
        if response is not None and response.status >= 500:
            if offset == 0:
                _log(
                    f"Yahoo refused the search (HTTP {response.status}). It does this "
                    "when the browser's User-Agent says 'HeadlessChrome' - check "
                    "USER_AGENT in sources/base.py."
                )
            return None
        if not self._await_human(page):
            return None
        try:
            page.wait_for_selector(
                TILE_SELECTOR, state="attached", timeout=self.nav_timeout_ms
            )
        except PlaywrightTimeoutError:
            if offset == 0:
                _log(
                    "Yahoo returned no image results - the markup may have "
                    "changed (update selectors in sources/yahoo.py)."
                )
            return None
        return (
            page.eval_on_selector_all(TILE_SELECTOR, _EXTRACT_JS),
            page.evaluate(_NEXT_OFFSET_JS),
        )

    def _is_off_results(self, page) -> bool:
        try:
            return urlparse(page.url).hostname != RESULTS_HOST
        except Exception:
            return False

    def _await_human(self, page) -> bool:
        if not self._is_off_results(page):
            return True
        host = urlparse(page.url).hostname
        if self.unattended:
            raise HumanInterventionRequired(
                f"Yahoo sent the browser to {host} instead of the results "
                "(usually a consent page)"
            )
        if not self.headful:
            _log(
                f"Yahoo sent the browser to {host} instead of the results (usually a "
                "consent page) and this is a headless run, so it can't be handled. "
                "Re-run with --headful to accept it by hand."
            )
            return False
        _log(
            f"Yahoo sent the browser to {host} - please handle it in the browser "
            f"window. Harvesting resumes automatically (waiting up to "
            f"{self.solve_timeout_ms // 1000}s)..."
        )
        deadline = time.monotonic() + self.solve_timeout_ms / 1000
        while self._is_off_results(page):
            if time.monotonic() > deadline:
                _log("Timed out waiting to get back to the results; stopping this search.")
                return False
            page.wait_for_timeout(1_000)
        _log("Back on the results - continuing.")
        return True
