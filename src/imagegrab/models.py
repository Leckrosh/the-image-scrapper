from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class ImageResult:

    image_url: str
    query: str
    source: str
    thumbnail_url: str | None = None
    source_page: str | None = None
    width: int | None = None
    height: int | None = None


@dataclass(slots=True)
class RunResult:

    counts: dict[str, int]
    # Why the run stopped for a person (--unattended only); None when it didn't.
    human_required: str | None = None
