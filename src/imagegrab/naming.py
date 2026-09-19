"""Filesystem-safe naming for kept images.

Kept images are laid out one folder per query (the class), with a zero-padded
per-query index in the filename:

    images/ferrari/ferrari_0001.jpg
    images/lamborghini/lamborghini_0001.png

However this logic may not be enough, still thinking for a more optimal approach.
Proposals are accepted to determine a better path.
"""

from __future__ import annotations

import re

INDEX_WIDTH = 4

_SEPARATORS = re.compile(r"[^\w-]+", re.UNICODE)


def slugify(query: str) -> str:
    text = _SEPARATORS.sub("_", query.strip().lower()).strip("_")
    return text or "images"


def image_filename(slug: str, index: int, ext: str) -> str:
    return f"{slug}_{index:0{INDEX_WIDTH}d}.{ext}"
