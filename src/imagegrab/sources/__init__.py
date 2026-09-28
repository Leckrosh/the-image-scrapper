from __future__ import annotations

from .base import ImageSource
from .bing import BingImagesSource
from .brave import BraveImagesSource
from .duckduckgo import DuckDuckGoImagesSource
from .google import GoogleImagesSource
from .yahoo import YahooImagesSource
from .yandex import YandexImagesSource

SOURCES: dict[str, type[ImageSource]] = {
    "bing": BingImagesSource,
    "google": GoogleImagesSource,
    "yandex": YandexImagesSource,
    "yahoo": YahooImagesSource,
    "brave": BraveImagesSource,
    "duckduckgo": DuckDuckGoImagesSource,
}

# Bing is selected as default only because is the 1st solution that works headless with no more human intervention
DEFAULT_SOURCE = "bing"

__all__ = ["SOURCES", "DEFAULT_SOURCE", "ImageSource", "build_source"]


def build_source(
    name: str,
    *,
    headful: bool = False,
    pace: float = 1.0,
    profile_dir: str | None = None,
) -> ImageSource:

    if name == "google":
        return GoogleImagesSource(headful=headful, pace=pace, profile_dir=profile_dir)
    if name == "bing":
        return BingImagesSource(headful=headful, pace=pace)
    if name == "yandex":
        return YandexImagesSource(headful=headful, pace=pace)
    if name == "yahoo":
        return YahooImagesSource(headful=headful, pace=pace)
    if name == "brave":
        return BraveImagesSource(headful=headful)
    if name == "duckduckgo":
        return DuckDuckGoImagesSource(headful=headful, pace=pace)
    raise ValueError(f"unknown source: {name!r} (choices: {', '.join(SOURCES)})")
