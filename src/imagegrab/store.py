from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Integer, String, create_engine, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from .dedup import hamming
from .models import ImageResult

KEPT = "downloaded"


class Base(DeclarativeBase):
    pass


class ImageRow(Base):

    __tablename__ = "images"

    id: Mapped[int] = mapped_column(primary_key=True)
    query: Mapped[str] = mapped_column(String, index=True)
    source: Mapped[str] = mapped_column(String)
    image_url: Mapped[str] = mapped_column(String, unique=True)
    source_page: Mapped[str | None] = mapped_column(String, nullable=True)
    thumbnail_url: Mapped[str | None] = mapped_column(String, nullable=True)
    local_path: Mapped[str | None] = mapped_column(String, nullable=True)
    byte_hash: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    phash: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String, index=True, default="pending")
    created_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc)
    )


class Store:

    def __init__(self, db_path: str) -> None:
        self.engine = create_engine(f"sqlite:///{db_path}")
        Base.metadata.create_all(self.engine)
        self.session = Session(self.engine, expire_on_commit=False)

    def add_candidate(self, result: ImageResult) -> ImageRow | None:
        row = ImageRow(
            query=result.query,
            source=result.source,
            image_url=result.image_url,
            source_page=result.source_page,
            thumbnail_url=result.thumbnail_url,
            width=result.width,
            height=result.height,
            status="pending",
        )
        self.session.add(row)
        try:
            self.session.commit()
        #Exception to handle duplicated URL's.
        except IntegrityError:
            self.session.rollback()
            return None
        return row

    def pending(self, query: str | None = None) -> list[ImageRow]:
        stmt = select(ImageRow).where(ImageRow.status == "pending")
        if query is not None:
            stmt = stmt.where(ImageRow.query == query)
        return list(self.session.scalars(stmt))

    def byte_hash_exists(self, byte_hash: str) -> bool:
        stmt = (
            select(func.count())
            .select_from(ImageRow)
            .where(ImageRow.byte_hash == byte_hash, ImageRow.status == KEPT)
        )
        return (self.session.scalar(stmt) or 0) > 0

    def near_duplicate(self, phash: str, threshold: int = 5) -> bool:
        stmt = select(ImageRow.phash).where(
            ImageRow.status == KEPT, ImageRow.phash.is_not(None)
        )
        for (other,) in self.session.execute(stmt):
            if hamming(phash, other) <= threshold:
                return True
        return False

    def mark(self, row: ImageRow | int, status: str, **fields) -> None:
        if isinstance(row, int):
            row = self.session.get(ImageRow, row)
        row.status = status
        for key, value in fields.items():
            setattr(row, key, value)
        self.session.commit()

    def counts(self, query: str | None = None) -> dict[str, int]:
        stmt = select(ImageRow.status, func.count()).group_by(ImageRow.status)
        if query is not None:
            stmt = stmt.where(ImageRow.query == query)
        return {status: count for status, count in self.session.execute(stmt)}

    def downloaded_count(self, query: str) -> int:
        return self.counts(query).get(KEPT, 0)
