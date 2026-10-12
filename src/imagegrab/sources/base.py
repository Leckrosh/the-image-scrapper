from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator

from ..models import ImageResult

#For experience, USER Agent is required to avoid possible limitations when scrapping.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


class HumanInterventionRequired(Exception):
    """A source hit a CAPTCHA (or similar) during an --unattended run, so nobody can solve it."""


class ImageSource(ABC):

    name: str = "base"
    # False -> the source only works with a visible browser, so it always runs headful.
    headless: bool = True
    # True -> the source usually needs a person (a CAPTCHA), so --unattended runs don't harvest it.
    needs_human: bool = False

    @abstractmethod
    def search(self, query: str, limit: int) -> Iterator[ImageResult]:
        raise NotImplementedError
