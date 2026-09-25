from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator

from ..models import ImageResult

#For experience, USER Agent is required to avoid possible limitations when scrapping.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


class ImageSource(ABC):

    name: str = "base"

    @abstractmethod
    def search(self, query: str, limit: int) -> Iterator[ImageResult]:
        raise NotImplementedError
