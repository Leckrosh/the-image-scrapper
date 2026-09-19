"""Google Images source (Playwright). This is the method that I found possible at September 2026

If Google Images is presenting problems it might be due to Google Images changes.

NOTES:

- Google Images is JS-rendered, so, the UI of a real browser is required no matter why, didn't found a 
way to make it without UI.
- For Google case, due to its antibot rules, a manual reCAPTCHA is required, I'm aware this involves a manual
step, but didn't figure out how to evade it, anyway, once that manual step is done, the automation continues without a problem.
So it's just an extra step if you choose Google Images as your Image source.
- The "--headful" flag won't work at all on Google.

Due to limitations and different approaches, in the roadmap is considered to automatically setup the download with the only valid
approach to download images, it has no sense to keep it, but I'll work on it on future releases.
"""

from __future__ import annotations

import sys
import time
from collections.abc import Iterator
from urllib.parse import parse_qs, quote_plus, urlsplit, urlunsplit

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from ..models import ImageResult
from .base import ImageSource

# For experience, USER Agent is recommended to be set no matter what kind of Image browser you are using.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# Please, if you need more timeout modify it here.
SOLVE_TIMEOUT_MS = 180_000

_LAUNCH_ARGS = ["--disable-blink-features=AutomationControlled"]
_IGNORE_DEFAULT_ARGS = ["--enable-automation"]

CONSENT_SELECTORS = [
    "#L2AGLb",
    "button:has-text('Accept all')",
    "button:has-text('Aceptar todo')",
    "button:has-text('I agree')",
    "button[aria-label*='Accept']",
]
GRID_THUMB_SELECTOR = "img[id^='dimg_']"
IMGRES_ANCHOR_SELECTOR = "a[href^='/imgres?']"
GRID_READY_SELECTOR = "img[id^='dimg_'], a[href^='/imgres?']"
SHOW_MORE_SELECTOR = (
    "input[type='button'][value*='more'], "
    "input[type='button'][value*='más'], "
    "button:has-text('Show more results')"
)
_NON_ORIGIN_MARKERS = (
    "gstatic.com",
    "encrypted-tbn",
    "googleusercontent.com",
)
_IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tiff")


def _imgurl_from_href(href: str) -> tuple[str | None, str | None]:
    query = parse_qs(urlsplit(href).query)
    imgurl = query.get("imgurl", [None])[0]
    imgrefurl = query.get("imgrefurl", [None])[0]
    return imgurl, imgrefurl


def _normalize_url(url: str) -> str:
    parts = urlsplit(url)
    if parts.query and parts.path.lower().endswith(_IMAGE_EXTS):
        return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
    return url


def _is_origin(url: str | None) -> bool:
    return bool(
        url
        and url.startswith("http")
        and not any(marker in url for marker in _NON_ORIGIN_MARKERS)
    )


def _log(message: str) -> None:
    print(f"[imagegrab] {message}", file=sys.stderr)


class GoogleImagesSource(ImageSource):

    name = "google"

    def __init__(
        self,
        headful: bool = False,
        pace: float = 1.0,
        profile_dir: str | None = None,
        nav_timeout_ms: int = 30_000,
        solve_timeout_ms: int = SOLVE_TIMEOUT_MS,
        max_stagnant_rounds: int = 4,
    ) -> None:
        self.headful = headful
        self.pace = pace
        self.profile_dir = profile_dir
        self.nav_timeout_ms = nav_timeout_ms
        self.solve_timeout_ms = solve_timeout_ms
        self.max_stagnant_rounds = max_stagnant_rounds

    def search(self, query: str, limit: int) -> Iterator[ImageResult]:
        url = f"https://www.google.com/search?q={quote_plus(query)}&udm=2&hl=en"
        with sync_playwright() as pw:
            browser, context, page = self._open_context(pw)
            page.set_default_timeout(self.nav_timeout_ms)
            try:
                page.goto(url, wait_until="domcontentloaded")
                self._dismiss_consent(page)
                if not self._await_human(page):
                    return
                self._dismiss_consent(page)
                yield from self._harvest(page, query, limit)
            finally:
                context.close()
                if browser is not None:
                    browser.close()

    def _open_context(self, pw):
        ctx_kwargs = dict(
            user_agent=USER_AGENT,
            locale="en-US",
            viewport={"width": 1366, "height": 900},
        )
        launch_kwargs = dict(
            headless=not self.headful,
            args=_LAUNCH_ARGS,
            ignore_default_args=_IGNORE_DEFAULT_ARGS,
        )

        if self.profile_dir:
            last_exc: Exception | None = None
            for channel in ("chrome", None):
                kwargs = dict(launch_kwargs, **ctx_kwargs)
                if channel:
                    kwargs["channel"] = channel
                try:
                    context = pw.chromium.launch_persistent_context(
                        self.profile_dir, **kwargs
                    )
                    page = context.pages[0] if context.pages else context.new_page()
                    return None, context, page
                except Exception as exc:
                    last_exc = exc
                    continue
            raise RuntimeError(
                f"could not open persistent profile at {self.profile_dir!r}: {last_exc}"
            )

        browser = pw.chromium.launch(**launch_kwargs)
        context = browser.new_context(**ctx_kwargs)
        page = context.new_page()
        return browser, context, page

    def _is_blocked(self, page) -> bool:
        try:
            return "/sorry" in page.url
        except Exception:
            return False

    def _await_human(self, page) -> bool:
        if not self._is_blocked(page):
            return True
        if not self.headful:
            _log(
                "Google served a CAPTCHA / 'unusual traffic' page and this is a "
                "headless run, so it can't be solved. Re-run with --headful "
                "(add --profile-dir <dir> to remember the solve across runs)."
            )
            return False
        _log(
            "CAPTCHA detected - please solve it in the browser window. "
            f"Harvesting resumes automatically (waiting up to "
            f"{self.solve_timeout_ms // 1000}s)..."
        )
        try:
            page.wait_for_url(
                lambda u: "/sorry" not in u, timeout=self.solve_timeout_ms
            )
            page.wait_for_selector(GRID_READY_SELECTOR, timeout=self.nav_timeout_ms)
        except PlaywrightTimeoutError:
            _log("Timed out waiting for the CAPTCHA to be solved; stopping this search.")
            return False
        _log("CAPTCHA cleared - continuing.")
        return True

    def _dismiss_consent(self, page) -> None:
        for selector in CONSENT_SELECTORS:
            try:
                button = page.query_selector(selector)
                if button and button.is_visible():
                    button.click()
                    page.wait_for_timeout(500)
                    return
            except Exception:
                continue

    def _harvest(self, page, query: str, limit: int) -> Iterator[ImageResult]:
        seen: set[str] = set()
        hovered = 0
        stagnant_rounds = 0

        while len(seen) < limit and stagnant_rounds < self.max_stagnant_rounds:
            thumbs = page.query_selector_all(GRID_THUMB_SELECTOR)

            if hovered >= len(thumbs):
                grew = self._scroll(page, len(thumbs))
                if self._is_blocked(page):
                    if not self._await_human(page):
                        break
                    continue
                stagnant_rounds = 0 if grew else stagnant_rounds + 1
                continue

            for i in range(hovered, len(thumbs)):
                if len(seen) >= limit:
                    break
                self._hover(thumbs[i])
                page.wait_for_timeout(120)
                for imgurl, imgrefurl in self._collect_imgres(page):
                    normalized = _normalize_url(imgurl)
                    if normalized in seen or not _is_origin(normalized):
                        continue
                    seen.add(normalized)
                    yield ImageResult(
                        image_url=normalized,
                        query=query,
                        source=self.name,
                        source_page=imgrefurl,
                    )
                    if len(seen) >= limit:
                        break
                if self.pace:
                    time.sleep(self.pace)

            hovered = len(thumbs)

    def _hover(self, thumb) -> bool:
        try:
            thumb.scroll_into_view_if_needed(timeout=3_000)
            thumb.hover(timeout=3_000)
            return True
        except Exception:
            return False

    def _collect_imgres(self, page):
        for anchor in page.query_selector_all(IMGRES_ANCHOR_SELECTOR):
            href = anchor.get_attribute("href")
            if not href:
                continue
            imgurl, imgrefurl = _imgurl_from_href(href)
            if imgurl:
                yield imgurl, imgrefurl

    def _scroll(self, page, prev_thumb_count: int) -> bool:
        page.mouse.wheel(0, 20_000)
        page.wait_for_timeout(1_200)
        try:
            button = page.query_selector(SHOW_MORE_SELECTOR)
            if button and button.is_visible():
                button.click()
                page.wait_for_timeout(1_200)
        except Exception:
            pass
        return len(page.query_selector_all(GRID_THUMB_SELECTOR)) > prev_thumb_count
