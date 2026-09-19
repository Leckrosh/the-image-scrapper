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
