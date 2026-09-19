"""De-duplication primitives, cheapest first.

Three layers, applied in order by the downloader:

1. exact URL  — enforced by a UNIQUE column in the store (not here).
2. exact bytes — ``sha256_bytes`` catches byte-identical re-encodes.
3. near-dup    — ``phash_bytes`` + ``hamming`` catch visually-similar images
                 (rescales, re-compressions, minor crops) within a Hamming
                 distance threshold.

All functions here operate on raw image ``bytes`` so they work equally on the
downloaded payload with no browser or file involved.
"""

from __future__ import annotations

import hashlib
import io

import imagehash
from PIL import Image


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def image_dims(data: bytes) -> tuple[int, int]:
    with Image.open(io.BytesIO(data)) as img:
        return img.size


def phash_bytes(data: bytes) -> str:
    with Image.open(io.BytesIO(data)) as img:
        return str(imagehash.phash(img))


def hamming(a: str, b: str) -> int:
    return imagehash.hex_to_hash(a) - imagehash.hex_to_hash(b)
