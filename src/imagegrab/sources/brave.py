"""
Brave Images source: Works for headless browser (and headful). September 27, 2026.

Brave didn't ask for a CAPTCHA in the browser.

NOTES:

- Brave serves images from its own index, so overlapping possibilities is low.
- There's no pagination: Brave returns at most 200 images per term. `offset`/`page` params are ignored and
  scrolling only renders images already on the page.
- The only problem is that, the vast majority of brave results are from stock photo sites. So, it tends, to retrieve
  low resolution images.
- SafeSearch is turned off with `&safesearch=off` in the URL (same effect as Brave's `safesearch` cookie).
- Even if the CAPTCHA didn't triggers, I left the same mechanism created for Google, waiting for human intervention
  if some manual verification is needed.

Please, if harvesting returns nothing, report it as an issue to update the method.
"""

from __future__ import annotations

import json
import re
import sys
import time
from collections.abc import Iterator
from urllib.parse import quote_plus

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

from ..models import ImageResult
from .base import USER_AGENT, ImageSource

# Please, if you need more time to solve the CAPTCHA modify it here.
SOLVE_TIMEOUT_MS = 180_000

# FRAGILE ZONE - Brave markup/URL. If harvesting returns nothing, this is the most probable section that needs to be updated.
IMAGES_SEARCH_URL = "https://search.brave.com/images"
DATA_SCRIPT_MARKER = "kit.start("
DATA_LITERAL_RE = re.compile(r"\bdata:\s*\[")
RESULTS_TYPE = "images"
TILE_SELECTOR = "button.image-result"
CAPTCHA_STATUS = 429
CAPTCHA_ROUTE_MARKER = 'page:"/captcha"'
MAX_RESULTS = 200
_SCRIPT_JS = r"""
marker => {
  const s = [...document.scripts].find(s => s.textContent.includes(marker));
  return s ? s.textContent : null;
}
"""

_SAFE_SEARCH = {"strict": "strict", "moderate": "moderate", "off": "off"}

_LAUNCH_ARGS = ["--disable-blink-features=AutomationControlled"]
_IGNORE_DEFAULT_ARGS = ["--enable-automation"]


def _log(message: str) -> None:
    print(f"[tis] {message}", file=sys.stderr)


def _array_literal(src: str, start: int) -> str | None:
    # The JS array literal opening at src[start] ('['), skipping over string contents.
    depth = 0
    quote = None
    i = start
    while i < len(src):
        ch = src[i]
        if quote:
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = None
        elif ch in "\"'`":
            quote = ch
        elif ch in "[{(":
            depth += 1
        elif ch in "]})":
            depth -= 1
            if depth == 0:
                return src[start : i + 1]
        i += 1
    return None


def _images_response(nodes: list) -> dict | None:
    # One node per SvelteKit route level (layout, page); the page node's body holds the search response.
    for node in nodes:
        data = node.get("data") if isinstance(node, dict) else None
        body = data.get("body") if isinstance(data, dict) else None
        response = body.get("response") if isinstance(body, dict) else None
        if isinstance(response, dict) and response.get("type") == RESULTS_TYPE:
            return response
    return None


class BraveImagesSource(ImageSource):

    name = "brave"

    def __init__(
        self,
        headful: bool = False,
        safe_search: str = "off",
        nav_timeout_ms: int = 30_000,
        solve_timeout_ms: int = SOLVE_TIMEOUT_MS,
    ) -> None:
        self.headful = headful
        self.safe_search = safe_search
        self.nav_timeout_ms = nav_timeout_ms
        self.solve_timeout_ms = solve_timeout_ms

    def search(self, query: str, limit: int) -> Iterator[ImageResult]:
        # Everything arrives in one page load, so the browser is closed before yielding (not left open during downloads).
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
                results = self._load_results(page, query)
            finally:
                context.close()
                browser.close()

        if results is None:
            return
        seen: set[str] = set()
        for item in results:
            murl = (item.get("properties") or {}).get("url")
            if not murl or murl in seen:
                continue
            seen.add(murl)
            yield ImageResult(
                image_url=murl,
                query=query,
                source=self.name,
                thumbnail_url=(item.get("thumbnail") or {}).get("src"),
                source_page=item.get("url"),
            )
            if len(seen) >= limit:
                return
        if not seen:
            _log("Brave returned no images for this term.")
        else:
            _log(
                f"Brave has no more results for this term ({len(seen)} found; it "
                f"returns at most ~{MAX_RESULTS} per term)."
            )

    def _load_results(self, page, query: str) -> list[dict] | None:
        safesearch = _SAFE_SEARCH.get(self.safe_search.lower(), "off")
        url = f"{IMAGES_SEARCH_URL}?q={quote_plus(query)}&safesearch={safesearch}"
        response = page.goto(url, wait_until="domcontentloaded")
        script = self._data_script(page)
        if self._is_blocked(response, script):
            if not self._await_human(page):
                return None
            # Load again so the page carries the results data, not the CAPTCHA's.
            response = page.goto(url, wait_until="domcontentloaded")
            script = self._data_script(page)
            if self._is_blocked(response, script):
                _log("Brave is still asking for a CAPTCHA; stopping this search.")
                return None

        nodes = self._page_data(page, script)
        response_data = _images_response(nodes) if nodes else None
        if response_data is None:
            _log(
                "Brave returned no image data - the markup may have changed "
                "(update the FRAGILE ZONE in sources/brave.py)."
            )
            return None
        return response_data.get("results") or []

    def _data_script(self, page) -> str | None:
        try:
            return page.evaluate(_SCRIPT_JS, DATA_SCRIPT_MARKER)
        except PlaywrightError:
            return None

    def _page_data(self, page, script: str | None) -> list | None:
        if not script:
            return None
        match = DATA_LITERAL_RE.search(script, script.find(DATA_SCRIPT_MARKER))
        literal = _array_literal(script, match.end() - 1) if match else None
        if literal is None:
            return None
        try:
            # The browser evaluates the page's own literal; written as a function so Playwright never guesses.
            return json.loads(page.evaluate(f"() => JSON.stringify({literal})"))
        except (PlaywrightError, ValueError):
            return None

    def _is_blocked(self, response, script: str | None) -> bool:
        if response is not None and response.status == CAPTCHA_STATUS:
            return True
        return bool(script) and CAPTCHA_ROUTE_MARKER in script

    def _captcha_cleared(self, page) -> bool:
        try:
            if page.query_selector(TILE_SELECTOR):
                return True
            script = self._data_script(page)
            return bool(script) and CAPTCHA_ROUTE_MARKER not in script
        except PlaywrightError:
            # The page is navigating (e.g. right after the CAPTCHA is solved).
            return False

    def _await_human(self, page) -> bool:
        if not self.headful:
            _log(
                "Brave is asking for a CAPTCHA (HTTP 429) and this is a headless "
                "run, so it can't be solved. Wait a few minutes, or re-run with "
                "--headful to solve it by hand."
            )
            return False
        _log(
            "CAPTCHA detected - please solve it in the browser window. "
            f"Harvesting resumes automatically (waiting up to "
            f"{self.solve_timeout_ms // 1000}s)..."
        )
        deadline = time.monotonic() + self.solve_timeout_ms / 1000
        while not self._captcha_cleared(page):
            if time.monotonic() > deadline:
                _log("Timed out waiting for the CAPTCHA to be solved; stopping this search.")
                return False
            page.wait_for_timeout(1_000)
        _log("CAPTCHA cleared - continuing.")
        return True
