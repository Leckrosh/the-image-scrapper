from __future__ import annotations

from collections import Counter
from collections.abc import Callable

from .downloader import Downloader
from .resolution import TIERS
from .sources import DEFAULT_SOURCE, build_source
from .store import KEPT, Store

# HARVEST_CEILING caps the NEW urls a run takes from a source; SCAN_CEILING caps
# how many results it looks at, already-stored ones included. Counting only new
# urls lets a later run get past the results an earlier run already stored.
HARVEST_CEILING = 1000
SCAN_CEILING = 3000
BATCH_SIZE = 40


def run(
    query: str,
    collect: int,
    max_total: int | None = None,
    unique_source: bool = False,
    min_resolution: str = "none",
    out_dir: str = "images",
    db_path: str = "imagegrab.db",
    source: str = DEFAULT_SOURCE,
    headful: bool = False,
    concurrency: int = 20,
    pace: float = 1.0,
    profile_dir: str | None = None,
    progress: Callable[[str], None] = print,
) -> dict[str, int]:
    tier = TIERS[min_resolution]
    store = Store(db_path)
    downloader = Downloader(store, out_dir, tier, concurrency=concurrency)

    stored = store.downloaded_count(query)
    goal = collect
    if max_total is not None:
        room = max_total - stored
        if room <= 0:
            progress(
                f"[tis] already at --max-total for '{query}' "
                f"(have {stored}, max {max_total}) - nothing to do."
            )
            return store.counts(query)
        if room < collect:
            progress(
                f"[tis] have {stored}; --collect {collect} trimmed to {room} "
                f"by --max-total {max_total}."
            )
            goal = room

    progress(
        f"[tis] '{query}' - collecting {goal} new "
        f"(min-resolution {min_resolution}); already have {stored}."
    )

    # Leftovers go first: no browser needed. Unless --unique-source is set they
    # come from every source that left some behind.
    only = source if unique_source else None
    leftovers: Counter[tuple[str, str]] = Counter()
    kept = 0

    reusable = store.reusable(query, tier, only)
    if reusable:
        fresh = downloader.drop_known_duplicates(reusable)
        if len(fresh) < len(reusable):
            progress(
                f"[tis] skipped {len(reusable) - len(fresh)} image(s) rejected as "
                "too small earlier: copies of images you already have."
            )
        if fresh:
            progress(
                f"[tis] {len(fresh)} image(s) rejected as too small earlier now pass "
                f"{_at_tier(min_resolution)}; reusing them first."
            )
            kept += _drain(downloader, fresh, goal - kept, leftovers)

    pending = store.pending(query, only)
    if pending and kept < goal:
        progress(f"[tis] resuming {len(pending)} pending candidate(s)...")
        kept += _drain(downloader, pending, goal - kept, leftovers)

    if leftovers:
        by_source = Counter(
            {name: n for (name, status), n in leftovers.items() if status == KEPT}
        )
        detail = ", ".join(f"{name} {n}" for name, n in by_source.most_common())
        line = f"[tis] leftovers gave {kept}" + (f" ({detail})" if detail else "")
        if kept >= goal:
            progress(f"{line}; {source} harvest not needed.")
            return _summary(store, query, kept, goal, progress)
        progress(f"{line}; harvesting {source} for the other {goal - kept}.")

    harvester = build_source(
        source, headful=headful, pace=pace, profile_dir=profile_dir
    )
    harvest: Counter[tuple[str, str]] = Counter()
    seen = 0
    new_urls = 0
    hit_ceiling = False
    batch = []

    for result in harvester.search(query, limit=SCAN_CEILING):
        seen += 1
        row = store.add_candidate(result)
        if row is not None:
            new_urls += 1
            batch.append(row)

        if len(batch) >= BATCH_SIZE:
            kept += _download(downloader, batch, goal - kept, harvest)
            batch.clear()
            progress(f"[tis] kept {kept}/{goal} (harvested {seen}, {new_urls} new)")
            if kept >= goal:
                break

        if new_urls >= HARVEST_CEILING:
            hit_ceiling = True
            break

    if batch and kept < goal:
        kept += _download(downloader, batch, goal - kept, harvest)
        progress(f"[tis] kept {kept}/{goal} (harvested {seen}, {new_urls} new)")

    if kept < goal:
        _diagnose(
            progress, source, query, min_resolution, seen, new_urls, hit_ceiling, harvest
        )

    return _summary(store, query, kept, goal, progress)


def _download(
    downloader: Downloader, rows, need: int, outcomes: Counter[tuple[str, str]]
) -> int:
    result = downloader.run(rows, max_keep=need)
    outcomes.update(result)
    return _by_status(result)[KEPT]


# Feeds rows in BATCH_SIZE chunks so a big leftover pile isn't fetched whole
# when only a few images are still needed.
def _drain(
    downloader: Downloader, rows, need: int, outcomes: Counter[tuple[str, str]]
) -> int:
    kept = 0
    for start in range(0, len(rows), BATCH_SIZE):
        if kept >= need:
            break
        chunk = rows[start : start + BATCH_SIZE]
        kept += _download(downloader, chunk, need - kept, outcomes)
    return kept


def _by_status(outcomes: Counter[tuple[str, str]]) -> Counter[str]:
    totals: Counter[str] = Counter()
    for (_, status), n in outcomes.items():
        totals[status] += n
    return totals


def _at_tier(min_resolution: str) -> str:
    if min_resolution == "none":
        return "with no minimum resolution"
    return f"at {min_resolution}"


# Explains why a harvest fell short of --collect: one breakdown line, then a
# headline picked from what happened to the NEW urls (not from what was kept).
def _diagnose(
    progress: Callable[[str], None],
    source: str,
    query: str,
    min_resolution: str,
    seen: int,
    new_urls: int,
    hit_ceiling: bool,
    outcomes: Counter[tuple[str, str]],
) -> None:
    if seen == 0:
        progress(
            f"[tis] {source} returned no results for '{query}' - "
            "blocked or no matches."
        )
        return

    status = _by_status(outcomes)
    kept = status[KEPT]
    below = status["too_small"]
    known = status["duplicate"] + status["near_duplicate"]
    failed = status["failed"]

    parts = [f"kept {kept}"]
    if min_resolution != "none":
        parts.append(f"below {min_resolution}: {below}")
    if known:
        parts.append(f"already have this image: {known}")
    if failed:
        parts.append(f"failed: {failed}")
    progress(
        f"[tis] {source}: {seen} result(s), {new_urls} new -> " + " | ".join(parts)
    )

    if hit_ceiling:
        msg = (
            f"hit the harvest ceiling ({HARVEST_CEILING} new results) - "
            "run again to continue."
        )
    elif seen >= SCAN_CEILING:
        msg = (
            f"looked at {SCAN_CEILING} results, the most one run checks, and found "
            f"only {new_urls} new - try a different source."
        )
    elif new_urls == 0:
        msg = (
            f"The source '{source}' is already exhausted for the term: '{query}' - "
            "try a different source."
        )
    else:
        worst = max(below, known, failed)
        if worst <= kept:
            msg = (
                f"'{source}' is running dry for '{query}': only {new_urls} new "
                "result(s) - try a different source."
            )
        elif worst == below:
            msg = (
                f"'{source}' is running dry for '{query}' at {min_resolution}+ - "
                "try a lower --min-resolution or a different source."
            )
        elif worst == known:
            msg = (
                f"'{source}' keeps returning images you already have for '{query}' "
                "(same picture, different URL)."
            )
        else:
            msg = f"'{source}' results for '{query}' are mostly dead or blocked links."
    progress(f"[tis] {msg}")


def _summary(
    store: Store, query: str, kept: int, goal: int, progress: Callable[[str], None]
) -> dict[str, int]:
    counts = store.counts(query)
    progress(
        f"[tis] done: +{kept} of {goal} new for '{query}' "
        f"({counts.get(KEPT, 0)} total)."
    )
    breakdown = ", ".join(f"{status}={n}" for status, n in sorted(counts.items()))
    progress(f"[tis] status breakdown: {breakdown or '(none)'}")
    return counts
