from __future__ import annotations

import argparse
import sys

from . import __version__
from .pipeline import run
from .resolution import TIERS
from .sources import DEFAULT_SOURCE, SOURCES

COUNT_CEILING = 1000


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
        "--count",
        type=int,
        default=50,
        help=(
            "Number of images to KEEP after dedup + resolution filtering "
            f"(default: 50; clamped to 1..{COUNT_CEILING})."
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
            "(headless browser, no CAPTCHA, no manual step). 'google' is richer "
            "but fragile and may need --headful to solve a CAPTCHA by hand."
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
            "Show the browser while harvesting. Required for Google to solve a "
            "CAPTCHA by hand; for Bing it's optional (just to watch/debug)."
        ),
    )
    parser.add_argument(
        "--profile-dir",
        default=None,
        help=(
            "Google only: persistent browser profile directory. Remembers consent "
            "+ CAPTCHA solves across runs - recommended with --headful. Use a "
            "dedicated folder, not your everyday Chrome profile. Ignored by "
            "--source bing."
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
            "on Google, scrolls on Bing (default: 1.0)."
        ),
    )
    parser.add_argument("--version", action="version", version=f"tis {__version__}")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    count = args.count
    if count < 1:
        print("[imagegrab] --count below 1; clamping to 1.", file=sys.stderr)
        count = 1
    elif count > COUNT_CEILING:
        print(
            f"[imagegrab] --count {count} exceeds the {COUNT_CEILING} ceiling; "
            f"clamping to {COUNT_CEILING}.",
            file=sys.stderr,
        )
        count = COUNT_CEILING

    run(
        query=args.query,
        count=count,
        min_resolution=args.min_resolution,
        out_dir=args.out,
        db_path=args.db,
        source=args.source,
        headful=args.headful,
        concurrency=args.concurrency,
        pace=args.pace,
        profile_dir=args.profile_dir,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
