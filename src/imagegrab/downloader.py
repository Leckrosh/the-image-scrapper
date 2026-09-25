"""

Downloading + filtering — no browser involved.

Once a full-res origin URL is harvested, fetching it is a plain HTTP GET. This
module fetches a batch of pending rows concurrently (network is the
bottleneck), then processes the results *sequentially* so SQLite stays
single-threaded and the dedup checks never race:

    fetch (async, N at a time)
        -> SHA-256   -> exact duplicate?      -> status=duplicate
        -> decode    -> undecodable?          -> status=failed
        -> pHash     -> near-duplicate?       -> status=near_duplicate
        -> min(w,h)  -> below the tier?        -> status=too_small
        -> otherwise -> save file, status=downloaded  (kept)
"""

from __future__ import annotations

import asyncio
import io
import threading
from pathlib import Path

import httpx
import imagehash
from PIL import Image, UnidentifiedImageError

from .dedup import sha256_bytes
from .naming import image_filename, slugify
from .resolution import passes
from .sources.base import USER_AGENT
from .store import Store

_EXT_BY_FORMAT = {
    "jpeg": "jpg",
    "png": "png",
    "webp": "webp",
    "gif": "gif",
    "bmp": "bmp",
    "tiff": "tiff",
}


class Downloader:

    def __init__(
        self,
        store: Store,
        out_dir: str,
        tier: int,
        concurrency: int = 20,
        timeout: float = 30.0,
    ) -> None:
        self.store = store
        self.out_dir = Path(out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.tier = tier
        self.concurrency = concurrency
        self.timeout = timeout
        self._next_index: dict[str, int] = {}

    def run(self, rows, max_keep: int | None = None) -> int:
        rows = list(rows)
        if not rows or (max_keep is not None and max_keep <= 0):
            return 0
        fetched = self._fetch_all_sync(rows)
        kept = 0
        for row_id, query, data, error in fetched:
            if max_keep is not None and kept >= max_keep:
                break
            kept += self._process(row_id, query, data, error)
        return kept

    def _fetch_all_sync(self, rows):
        box: dict = {}

        def worker() -> None:
            try:
                box["value"] = asyncio.run(self._fetch_all(rows))
            except BaseException as exc:
                box["error"] = exc

        thread = threading.Thread(target=worker, name="imagegrab-fetch")
        thread.start()
        thread.join()
        if "error" in box:
            raise box["error"]
        return box["value"]

    async def _fetch_all(self, rows):
        semaphore = asyncio.Semaphore(self.concurrency)

        headers = {"User-Agent": USER_AGENT}
        async with httpx.AsyncClient(
            headers=headers, timeout=self.timeout, follow_redirects=True
        ) as client:
            tasks = [
                self._fetch_one(client, semaphore, row.id, row.query, row.image_url)
                for row in rows
            ]
            return await asyncio.gather(*tasks)

    async def _fetch_one(self, client, semaphore, row_id: int, query: str, url: str):
        async with semaphore:
            try:
                response = await client.get(url)
                response.raise_for_status()
                return (row_id, query, response.content, None)
            except Exception as exc:  # network, HTTP, timeout — all non-fatal
                return (row_id, query, None, str(exc))

    def _next_seq(self, query: str) -> tuple[str, int]:
        slug = slugify(query)
        if slug not in self._next_index:
            self._next_index[slug] = self.store.downloaded_count(query)
        self._next_index[slug] += 1
        return slug, self._next_index[slug]

    def _process(
        self, row_id: int, query: str, data: bytes | None, error: str | None
    ) -> int:
        if error or not data:
            self.store.mark(row_id, "failed")
            return 0

        byte_hash = sha256_bytes(data)
        if self.store.byte_hash_exists(byte_hash):
            self.store.mark(row_id, "duplicate", byte_hash=byte_hash)
            return 0

        try:
            with Image.open(io.BytesIO(data)) as img:
                img.load()
                width, height = img.size
                fmt = (img.format or "").lower()
                phash = str(imagehash.phash(img))
        except (UnidentifiedImageError, OSError, ValueError):
            self.store.mark(row_id, "failed", byte_hash=byte_hash)
            return 0

        if self.store.near_duplicate(phash):
            self.store.mark(
                row_id,
                "near_duplicate",
                byte_hash=byte_hash,
                phash=phash,
                width=width,
                height=height,
            )
            return 0

        if not passes(width, height, self.tier):
            self.store.mark(
                row_id,
                "too_small",
                byte_hash=byte_hash,
                phash=phash,
                width=width,
                height=height,
            )
            return 0

        ext = _EXT_BY_FORMAT.get(fmt, "jpg")
        slug, index = self._next_seq(query)
        subdir = self.out_dir / slug
        subdir.mkdir(parents=True, exist_ok=True)
        path = subdir / image_filename(slug, index, ext)
        path.write_bytes(data)
        self.store.mark(
            row_id,
            "downloaded",
            byte_hash=byte_hash,
            phash=phash,
            width=width,
            height=height,
            bytes=len(data),
            local_path=str(path),
        )
        return 1
