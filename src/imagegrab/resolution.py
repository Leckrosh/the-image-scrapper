"""

Resolution tiers were thinked as an optional flag to get images of specific resolutions if needed.

The rules were intentionally simple.

e.g

1080p min resolution

    passes(1080, 1920, 1080) -> True     # min(1080, 1920) == 1080 >= 1080
    passes(1010, 2500, 1080) -> False     # min(1010, 2500) == 1010  < 1080

When no resolution is set, then there will be no minimum resolution.

"""

from __future__ import annotations

TIERS: dict[str, int] = {
    "none": 0,
    "480p": 480,
    "720p": 720,
    "1080p": 1080,
    "4k": 2160,
}


def passes(width: int, height: int, tier: int) -> bool:
    return min(width, height) >= tier
