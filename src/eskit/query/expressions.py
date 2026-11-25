"""Composable query expressions: F("price") >= 10, a & b, a | b, ~a."""

from __future__ import annotations

import copy
from collections.abc import Iterable
from typing import Any


def _clean(params: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in params.items() if v is not None}


class Expr:
    """Base class of every query expression."""

    def to_dict(self) -> dict[str, Any]:
        raise NotImplementedError

    def __and__(self, other: Any) -> Expr:
        return And(self, ensure(other))

    def __or__(self, other: Any) -> Expr:
        return Or(self, ensure(other))

    def __invert__(self) -> Expr:
        return Not(self)

    def __bool__(self) -> bool:
        raise TypeError("Use &, | and ~ to combine queries (not `and`, `or`, `not`).")

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.to_dict()})"


class Raw(Expr):
    """Any raw query dict. Use it for features without a helper."""

    def __init__(self, body: dict[str, Any]) -> None:
        self._body = copy.deepcopy(body)

    def to_dict(self) -> dict[str, Any]:
        return copy.deepcopy(self._body)


def ensure(value: Any) -> Expr:
    """Accept an Expr, a dict, or an elasticsearch.dsl query (anything with to_dict)."""
    if isinstance(value, Expr):
        return value
    if isinstance(value, dict):
        return Raw(value)
    if callable(getattr(value, "to_dict", None)):
        return Raw(value.to_dict())
    raise TypeError(f"Not a query: {value!r}")


class _Group(Expr):
    def __init__(self, *parts: Expr) -> None:
        # Flatten a & b & c into one bool query.
        self.parts: list[Expr] = []
        for part in parts:
            self.parts.extend(part.parts if type(part) is type(self) else [part])


class And(_Group):
    def to_dict(self) -> dict[str, Any]:
        return {"bool": {"must": [p.to_dict() for p in self.parts]}}


class Or(_Group):
    def to_dict(self) -> dict[str, Any]:
        return {"bool": {"should": [p.to_dict() for p in self.parts], "minimum_should_match": 1}}


class Not(Expr):
    def __init__(self, inner: Expr) -> None:
        self.inner = inner

    def __invert__(self) -> Expr:
        return self.inner

    def to_dict(self) -> dict[str, Any]:
        return {"bool": {"must_not": [self.inner.to_dict()]}}


class F:
    """A document field. Comparison operators and methods return expressions."""

    def __init__(self, name: str) -> None:
        self.name = name

    __hash__ = None  # type: ignore[assignment]

    def _query(self, kind: str, value: Any) -> Raw:
        return Raw({kind: {self.name: value}})

    # exact values (use on keyword, numeric, date and boolean fields)
    def __eq__(self, value: object) -> Expr:  # type: ignore[override]
        if value is None:
            return ~self.exists()
        return self._query("term", {"value": value})

    def __ne__(self, value: object) -> Expr:  # type: ignore[override]
        return ~(self == value)

    def isin(self, values: Iterable[Any]) -> Expr:
        if isinstance(values, str):
            raise TypeError("isin() expects a list of values, not a string.")
        return self._query("terms", list(values))

    # ranges
    def range(self, *, gt: Any = None, gte: Any = None, lt: Any = None, lte: Any = None) -> Expr:
        bounds = _clean({"gt": gt, "gte": gte, "lt": lt, "lte": lte})
        if not bounds:
            raise ValueError(f"range() on {self.name!r} needs at least one bound.")
        return self._query("range", bounds)

    def between(self, low: Any, high: Any) -> Expr:
        """Inclusive range. Either side may be None (open ended)."""
        return self.range(gte=low, lte=high)

    def __gt__(self, value: Any) -> Expr:
        return self.range(gt=value)

    def __ge__(self, value: Any) -> Expr:
        return self.range(gte=value)

    def __lt__(self, value: Any) -> Expr:
        return self.range(lt=value)

    def __le__(self, value: Any) -> Expr:
        return self.range(lte=value)

    def exists(self) -> Expr:
        return Raw({"exists": {"field": self.name}})

    # full text
    def match(self, text: str, **options: Any) -> Expr:
        return self._query("match", {"query": text, **_clean(options)})

    def phrase(self, text: str, slop: int | None = None) -> Expr:
        return self._query("match_phrase", _clean({"query": text, "slop": slop}))

    def fuzzy(self, text: str, fuzziness: str | int = "AUTO") -> Expr:
        return self.match(text, fuzziness=fuzziness)

    def prefix(self, value: str) -> Expr:
        return self._query("prefix", {"value": value})

    def contains(self, value: str, case_insensitive: bool = True) -> Expr:
        """Substring search. User input is escaped. Slow on large indices."""
        escaped = value.replace("\\", "\\\\").replace("*", "\\*").replace("?", "\\?")
        return self._query(
            "wildcard", {"value": f"*{escaped}*", "case_insensitive": case_insensitive}
        )


def match_all() -> Expr:
    return Raw({"match_all": {}})


def multi_match(text: str, fields: list[str], **options: Any) -> Expr:
    return Raw({"multi_match": {"query": text, "fields": list(fields), **_clean(options)}})


def nested(path: str, query: Any, **options: Any) -> Expr:
    return Raw({"nested": {"path": path, "query": ensure(query).to_dict(), **_clean(options)}})
