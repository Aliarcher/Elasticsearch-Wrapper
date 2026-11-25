"""Typed view over a raw search response."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class Hit(Generic[T]):
    id: str
    index: str
    score: float | None
    source: T
    sort: list[Any] | None = None
    highlight: dict[str, list[str]] = field(default_factory=dict)


@dataclass(frozen=True)
class SearchResult(Generic[T]):
    hits: list[Hit[T]]
    total: int | None
    total_is_exact: bool
    took_ms: int
    timed_out: bool
    failed_shards: int
    aggregations: dict[str, Any]
    raw: Mapping[str, Any] = field(repr=False)

    @property
    def items(self) -> list[T]:
        return [hit.source for hit in self.hits]

    @property
    def next_search_after(self) -> list[Any] | None:
        return self.hits[-1].sort if self.hits else None

    @property
    def is_partial(self) -> bool:
        return self.timed_out or self.failed_shards > 0

    def __iter__(self) -> Iterator[T]:
        return iter(self.items)

    def __len__(self) -> int:
        return len(self.hits)

    @classmethod
    def from_response(cls, response: Mapping[str, Any], load: Any) -> SearchResult[Any]:
        block = response["hits"]
        total = block.get("total")
        hits = [
            Hit(
                id=h["_id"],
                index=h["_index"],
                score=h.get("_score"),
                source=load(h.get("_source", {}), h["_id"]),
                sort=h.get("sort"),
                highlight=h.get("highlight", {}),
            )
            for h in block.get("hits", [])
        ]
        return cls(
            hits=hits,
            total=total["value"] if total else None,
            total_is_exact=bool(total) and total["relation"] == "eq",
            took_ms=response.get("took", 0),
            timed_out=response.get("timed_out", False),
            failed_shards=response.get("_shards", {}).get("failed", 0),
            aggregations=response.get("aggregations", {}),
            raw=response,
        )
