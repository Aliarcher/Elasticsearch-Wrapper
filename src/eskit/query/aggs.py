"""Small, chainable aggregation builder."""

from __future__ import annotations

import copy
from typing import Any

from .expressions import ensure


class Agg:
    def __init__(self, kind: str, params: dict[str, Any]) -> None:
        self.kind = kind
        self.params = params
        self.children: dict[str, Agg] = {}

    def sub(self, name: str, agg: Agg) -> Agg:
        """Return a copy with a sub-aggregation added."""
        clone = copy.deepcopy(self)
        clone.children[name] = agg
        return clone

    def to_dict(self) -> dict[str, Any]:
        body: dict[str, Any] = {self.kind: copy.deepcopy(self.params)}
        if self.children:
            body["aggs"] = {name: child.to_dict() for name, child in self.children.items()}
        return body

    @classmethod
    def terms(cls, field: str, size: int = 10, **options: Any) -> Agg:
        return cls("terms", {"field": field, "size": size, **options})

    @classmethod
    def avg(cls, field: str) -> Agg:
        return cls("avg", {"field": field})

    @classmethod
    def sum(cls, field: str) -> Agg:
        return cls("sum", {"field": field})

    @classmethod
    def min(cls, field: str) -> Agg:
        return cls("min", {"field": field})

    @classmethod
    def max(cls, field: str) -> Agg:
        return cls("max", {"field": field})

    @classmethod
    def stats(cls, field: str) -> Agg:
        return cls("stats", {"field": field})

    @classmethod
    def cardinality(cls, field: str) -> Agg:
        return cls("cardinality", {"field": field})

    @classmethod
    def date_histogram(cls, field: str, calendar_interval: str, **options: Any) -> Agg:
        return cls(
            "date_histogram",
            {"field": field, "calendar_interval": calendar_interval, **options},
        )

    @classmethod
    def histogram(cls, field: str, interval: float, **options: Any) -> Agg:
        return cls("histogram", {"field": field, "interval": interval, **options})

    @classmethod
    def ranges(cls, field: str, ranges: list[dict[str, Any]]) -> Agg:
        return cls("range", {"field": field, "ranges": ranges})

    @classmethod
    def filter(cls, query: Any) -> Agg:
        return cls("filter", ensure(query).to_dict())

    @classmethod
    def nested(cls, path: str) -> Agg:
        return cls("nested", {"path": path})
