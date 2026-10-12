from __future__ import annotations

import argparse
import sys

from . import __version__
from .pipeline import run
from .resolution import TIERS
from .sources import DEFAULT_SOURCE, SOURCES

COLLECT_CEILING = 1000
# 1 and 2 are left to Python errors and argparse usage errors.
EXIT_HUMAN_REQUIRED = 3

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tis",
        description=(
            "Type a search term, get N de-duplicated images of at least a "
            "chosen resolution into a folder."
        ),
    )
    parser.add_argument("query", help="Search term, e.g. \"Ferrari Italia\".")
    parser.add_argument(
        "--collect",
        type=int,
        default=50,
        help=(
            "Number of NEW images to keep this run (after dedup + resolution "
            "filtering), on top of what is already stored for the term "
            f"(default: 50; clamped to 1..{COLLECT_CEILING})."
        ),
    )
    parser.add_argument(
        "--max-total",
        type=int,
        default=None,
        help=(
            "Never let the term's folder go past this many images in total, "
            "whatever --collect says. Applies to this run only (not saved)."
        ),
    )
    parser.add_argument(
        "--min-resolution",
        choices=list(TIERS),
        default="none",
        help="Minimum shorter-side resolution tier (default: none).",
    )
    parser.add_argument(
        "--source",
        choices=list(SOURCES),
        default=DEFAULT_SOURCE,
        help=(
            f"Harvest source (default: {DEFAULT_SOURCE}). 'bing' is hands-off "
            "(headless browser, no CAPTCHA, no manual step). 'yandex' is also "
            "headless; if it ever asks for a CAPTCHA, re-run with --headful to "
            "solve it. 'yahoo' is headless too (a few hundred images per term at "
            "most). 'brave' is headless too and has its own index, so its images "
            "barely overlap with the others (at most ~200 per term). 'duckduckgo' "
            "always runs headful (it refuses headless browsers); no manual step, "
            "a few hundred images per term. 'google' is richer but fragile; it "
            "always runs headful so you can solve its CAPTCHA by hand."
        ),
    )
    parser.add_argument(
        "--unique-source",
        action="store_true",
        help=(
            "Use only the chosen --source. By default, leftover URLs found earlier "
            "by ANY source are downloaded first; with this flag, leftovers from "
            "other sources are skipped (this source's own are still used)."
        ),
    )
    parser.add_argument(
        "--out",
        default="images",
        help=(
            "Root output folder. Kept images go under <out>/<query>/ as "
            "<query>_0001.jpg, so multiple searches stay separated (default: images)."
        ),
    )
    parser.add_argument(
        "--db",
        default="imagegrab.db",
        help="SQLite manifest path (default: imagegrab.db).",
    )
    parser.add_argument(
        "--headful",
        action="store_true",
        help=(
            "Show the browser for the sources that run headless by default: on "
            "Yandex and Brave it pauses for you to solve a CAPTCHA only if one "
            "shows up; on Yahoo it pauses only if you're sent to a consent page; "
            "for Bing it's just to watch/debug. Not needed for Google and "
            "DuckDuckGo: they always run headful."
        ),
    )
    parser.add_argument(
        "--unattended",
        action="store_true",
        help=(
            "Nobody is at the keyboard (e.g. batch scripts): never wait for a "
            "person. If a source asks for a CAPTCHA the run stops, keeps what it "
            f"already downloaded and exits with code {EXIT_HUMAN_REQUIRED}. Google "
            "is not harvested at all (it needs a CAPTCHA solved by hand); "
            "leftovers already stored are still used."
        ),
    )
    parser.add_argument(
        "--profile-dir",
        default=None,
        help=(
            "Google only: persistent browser profile directory. Remembers consent "
            "+ CAPTCHA solves across runs. Use a dedicated folder, not your "
            "everyday Chrome profile. Ignored by "
            "--source bing, yandex, yahoo, brave and duckduckgo."
        ),
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=20,
        help="Max simultaneous downloads (default: 20).",
    )
    parser.add_argument(
        "--pace",
        type=float,
        default=1.0,
        help=(
            "Seconds to wait between actions while harvesting - thumbnail hovers "
            "on Google, scrolls on Bing and DuckDuckGo, result pages on Yandex and "
            "Yahoo; unused on Brave, which loads a single page per term "
            "(default: 1.0)."
        ),
    )
    parser.add_argument("--version", action="version", version=f"tis {__version__}")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    collect = args.collect
    if collect < 1:
        print("[tis] --collect below 1; clamping to 1.", file=sys.stderr)
        collect = 1
    elif collect > COLLECT_CEILING:
        print(
            f"[tis] --collect {collect} exceeds the {COLLECT_CEILING} ceiling; "
            f"clamping to {COLLECT_CEILING}.",
            file=sys.stderr,
        )
        collect = COLLECT_CEILING

    if args.max_total is not None and args.max_total < 1:
        parser.error("--max-total must be at least 1")

    result = run(
        query=args.query,
        collect=collect,
        max_total=args.max_total,
        unique_source=args.unique_source,
        min_resolution=args.min_resolution,
        out_dir=args.out,
        db_path=args.db,
        source=args.source,
        headful=args.headful,
        concurrency=args.concurrency,
        pace=args.pace,
        profile_dir=args.profile_dir,
        unattended=args.unattended,
    )
    return EXIT_HUMAN_REQUIRED if result.human_required else 0


if __name__ == "__main__":
    raise SystemExit(main())
