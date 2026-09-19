"""Orchestration: harvest -> download/filter until enough images are kept.

The pipeline is fully synchronous for now, at least because of the requirements for getting images
from google images.

Stopping conditions:
    * ``count`` images kept (the target), or
    * Google is exhausted (harvest yields no more), or
    * the hard per-search harvest ceiling is hit.
"""

from __future__ import annotations

from collections.abc import Callable

from .downloader import Downloader
from .resolution import TIERS
from .sources.google import GoogleImagesSource
from .store import Store

HARVEST_CEILING = 1000
BATCH_SIZE = 40


def run(
    query: str,
    count: int,
    min_resolution: str = "none",
    out_dir: str = "images",
    db_path: str = "imagegrab.db",
    headful: bool = False,
    concurrency: int = 20,
    pace: float = 1.0,
    profile_dir: str | None = None,
    progress: Callable[[str], None] = print,
) -> dict[str, int]:
    tier = TIERS[min_resolution]
    store = Store(db_path)
    downloader = Downloader(store, out_dir, tier, concurrency=concurrency)

    kept = store.counts(query).get("downloaded", 0)
    progress(
        f"[imagegrab] '{query}' - target {count} kept "
        f"(min-resolution {min_resolution}); already have {kept}."
    )

    leftover = store.pending(query)
    if leftover and kept < count:
        progress(f"[imagegrab] resuming {len(leftover)} pending candidate(s)...")
        kept += downloader.run(leftover, max_keep=count - kept)

    if kept >= count:
        progress(f"[imagegrab] target already met ({kept}/{count}).")
        return _summary(store, query, kept, count, progress)

    source = GoogleImagesSource(headful=headful, pace=pace, profile_dir=profile_dir)
    harvested = 0
    batch = []

    for result in source.search(query, limit=HARVEST_CEILING):
        harvested += 1
        row = store.add_candidate(result)
        if row is not None:
            batch.append(row)

        if len(batch) >= BATCH_SIZE:
            kept += downloader.run(batch, max_keep=count - kept)
            batch.clear()
            progress(f"[imagegrab] kept {kept}/{count} (harvested {harvested})")
            if kept >= count:
                break

        if harvested >= HARVEST_CEILING:
            progress(f"[imagegrab] hit harvest ceiling ({HARVEST_CEILING}).")
            break

    if batch and kept < count:
        kept += downloader.run(batch, max_keep=count - kept)
        progress(f"[imagegrab] kept {kept}/{count} (harvested {harvested})")

    return _summary(store, query, kept, count, progress)


def _summary(
    store: Store, query: str, kept: int, count: int, progress: Callable[[str], None]
) -> dict[str, int]:
    counts = store.counts(query)
    progress(f"[imagegrab] done: {kept}/{count} kept for '{query}'.")
    breakdown = ", ".join(f"{status}={n}" for status, n in sorted(counts.items()))
    progress(f"[imagegrab] status breakdown: {breakdown or '(none)'}")
    return counts
