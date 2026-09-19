from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator

from ..models import ImageResult


class ImageSource(ABC):

    name: str = "base"

    @abstractmethod
    def search(self, query: str, limit: int) -> Iterator[ImageResult]:
        raise NotImplementedError
