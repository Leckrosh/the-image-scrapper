"""
Yandex Images source: Works for headless browser (and headful). September 25, 2026.

Yandex didn't ask for a CAPTCHA normally, however is noticed that its SmartCaptcha is triggered
by request volume / IP reputation, not by the automated browser itself.

NOTES:

- Results are server-rendered: each page embeds a JSON blob on the `ImagesApp-*` element's `data-state` attribute,
  every image there carries:
      origUrl -> full-resolution origin URL, image -> thumbnail, snippet.url -> page where the image lives.
- Scrolling loads more results through an XHR that does NOT update that blob, so instead of scrolling, pages are
  requested with `&p=N` (0-based, ~30 new images per page). Anyway, Yandex stops around p=50 (HTTP 404). This allows ~1.5K images per term.
- If the CAPTCHA shows up it comes back as a normal page (HTTP 200), so it's detected by URL/markup. With --headful the
  run requires human intervention (same as Google), headless just stops with a message.
- Yandex's family filter is left on its default (Moderate), but it might be turned off depending on what is being searched.
- Results tends to redirect to Russian sites (e.g. several photos of the same avto.ru listing), dedup takes care of near-duplicates.

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

# Please, if you need more time to solve the CAPTCHA modify it here.
SOLVE_TIMEOUT_MS = 180_000

# FRAGILE ZONE - Yandex markup/URL. If harvesting returns nothing, this is the most probable section that needs to be updated.
IMAGES_SEARCH_URL = "https://yandex.com/images/search"
STATE_SELECTOR = "[id^='ImagesApp-'][data-state]"
MAX_PAGES = 50
CAPTCHA_URL_MARKER = "showcaptcha"
# Not seen live yet (no CAPTCHA during testing), taken from public reports of the SmartCaptcha page.
CAPTCHA_SELECTOR = "form[action*='checkcaptcha'], .CheckboxCaptcha, .AdvancedCaptcha"
_EXTRACT_JS = r"""
els => {
  const out = [];
  const walk = o => {
    if (Array.isArray(o)) { o.forEach(walk); return; }
    if (!o || typeof o !== 'object') return;
    if (typeof o.origUrl === 'string') {
      out.push({murl: o.origUrl, turl: o.image || null, purl: (o.snippet && o.snippet.url) || null});
      return;
    }
    Object.values(o).forEach(walk);
  };
  els.forEach(el => { try { walk(JSON.parse(el.getAttribute('data-state'))); } catch (e) {} });
  return out;
}
"""

_LAUNCH_ARGS = ["--disable-blink-features=AutomationControlled"]
_IGNORE_DEFAULT_ARGS = ["--enable-automation"]


def _log(message: str) -> None:
    print(f"[imagegrab] {message}", file=sys.stderr)


def _absolute(url: str | None) -> str | None:
    # Yandex thumbnails are protocol-relative ("//avatars.mds.yandex.net/...").
    if url and url.startswith("//"):
        return f"https:{url}"
    return url


class YandexImagesSource(ImageSource):

    name = "yandex"

    def __init__(
        self,
        headful: bool = False,
        pace: float = 1.0,
        nav_timeout_ms: int = 30_000,
        solve_timeout_ms: int = SOLVE_TIMEOUT_MS,
        max_stagnant_rounds: int = 2,
    ) -> None:
        self.headful = headful
        self.pace = pace
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

        for page_no in range(MAX_PAGES):
            tiles = self._load_page(page, query, page_no)
            if tiles is None:
                return

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
                    thumbnail_url=_absolute(tile.get("turl")),
                    source_page=tile.get("purl"),
                )
                if len(seen) >= limit:
                    return

            stagnant_rounds = 0 if new_this_round else stagnant_rounds + 1
            if stagnant_rounds >= self.max_stagnant_rounds:
                return
            if self.pace:
                time.sleep(self.pace)

    def _load_page(self, page, query: str, page_no: int) -> list[dict] | None:
        url = f"{IMAGES_SEARCH_URL}?text={quote_plus(query)}&p={page_no}"
        response = page.goto(url, wait_until="domcontentloaded")
        if not self._await_human(page):
            return None
        # Past the last page Yandex answers 404: the results simply ran out.
        if response is not None and response.status == 404 and page_no > 0:
            return None
        try:
            page.wait_for_selector(
                STATE_SELECTOR, state="attached", timeout=self.nav_timeout_ms
            )
        except PlaywrightTimeoutError:
            if page_no == 0:
                _log(
                    "Yandex returned no image results - the markup may have "
                    "changed (update selectors in sources/yandex.py)."
                )
            return None
        return page.eval_on_selector_all(STATE_SELECTOR, _EXTRACT_JS)

    def _is_blocked(self, page) -> bool:
        try:
            return CAPTCHA_URL_MARKER in page.url or bool(
                page.query_selector(CAPTCHA_SELECTOR)
            )
        except Exception:
            return False

    def _await_human(self, page) -> bool:
        if not self._is_blocked(page):
            return True
        if not self.headful:
            _log(
                "Yandex is asking for a CAPTCHA (usually too many requests from "
                "this IP) and this is a headless run, so it can't be solved. Wait "
                "a few minutes, or re-run with --headful to solve it by hand."
            )
            return False
        _log(
            "CAPTCHA detected - please solve it in the browser window. "
            f"Harvesting resumes automatically (waiting up to "
            f"{self.solve_timeout_ms // 1000}s)..."
        )
        # Polled rather than wait_for_url: the challenge may be spotted by its markup, not only its URL.
        deadline = time.monotonic() + self.solve_timeout_ms / 1000
        while self._is_blocked(page):
            if time.monotonic() > deadline:
                _log("Timed out waiting for the CAPTCHA to be solved; stopping this search.")
                return False
            page.wait_for_timeout(1_000)
        _log("CAPTCHA cleared - continuing.")
        return True
