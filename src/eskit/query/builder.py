"""Immutable, fluent search-body builder."""

from __future__ import annotations

import copy
from collections.abc import Callable
from typing import Any

from .aggs import Agg
from .expressions import ensure

MAX_RESULT_WINDOW = 10_000


class QueryBuilder:
    """Every method returns a new builder, so a base query is safe to reuse."""

    def __init__(self) -> None:
        self._clauses: dict[str, list[dict[str, Any]]] = {}
        self._body: dict[str, Any] = {}
        self._msm: int | str | None = None

    def _clone(self) -> QueryBuilder:
        return copy.deepcopy(self)

    def _add(self, occur: str, queries: tuple[Any, ...]) -> QueryBuilder:
        clone = self._clone()
        for query in queries:
            if query is not None:  # None means "optional filter not provided"
                clone._clauses.setdefault(occur, []).append(ensure(query).to_dict())
        return clone

    def _set(self, key: str, value: Any) -> QueryBuilder:
        clone = self._clone()
        clone._body[key] = copy.deepcopy(value)
        return clone

    # ---- bool clauses ----
    def must(self, *queries: Any) -> QueryBuilder:
        """Must match, contributes to the score."""
        return self._add("must", queries)

    def filter(self, *queries: Any) -> QueryBuilder:
        """Must match, no scoring, cacheable."""
        return self._add("filter", queries)

    def should(self, *queries: Any, minimum_should_match: int | str | None = None) -> QueryBuilder:
        clone = self._add("should", queries)
        if minimum_should_match is not None:
            clone._msm = minimum_should_match
        return clone

    def exclude(self, *queries: Any) -> QueryBuilder:
        return self._add("must_not", queries)

    def when(self, value: Any, apply: Callable[[QueryBuilder, Any], QueryBuilder]) -> QueryBuilder:
        """Apply only if value is not None / "" / empty. 0 and False are kept."""
        if value is None or (hasattr(value, "__len__") and len(value) == 0):
            return self
        return apply(self, value)

    # ---- everything else ----
    def sort(self, *fields: str | dict[str, Any]) -> QueryBuilder:
        """sort("-price", "name") means price descending, then name ascending."""
        items: list[Any] = []
        for item in fields:
            if isinstance(item, str) and item.startswith("-"):
                items.append({item[1:]: {"order": "desc"}})
            elif isinstance(item, str) and item != "_score":
                items.append({item: {"order": "asc"}})
            else:
                items.append(item)
        return self._set("sort", items)

    def size(self, size: int) -> QueryBuilder:
        if size < 0:
            raise ValueError("size must be >= 0")
        return self._set("size", size)

    def offset(self, offset: int) -> QueryBuilder:
        if offset < 0:
            raise ValueError("offset must be >= 0")
        return self._set("from", offset)

    def paginate(self, page: int = 1, per_page: int = 10) -> QueryBuilder:
        if page < 1 or per_page < 1:
            raise ValueError("page and per_page must be >= 1")
        if page * per_page > MAX_RESULT_WINDOW:
            raise ValueError(
                f"Offset pagination is limited to {MAX_RESULT_WINDOW} results by default; "
                "use search_after() or Repository.iter_all()."
            )
        return self.offset((page - 1) * per_page).size(per_page)

    def search_after(self, values: list[Any]) -> QueryBuilder:
        return self._set("search_after", values)

    def source(
        self, includes: list[str] | None = None, excludes: list[str] | None = None
    ) -> QueryBuilder:
        spec = {}
        if includes is not None:
            spec["includes"] = includes
        if excludes is not None:
            spec["excludes"] = excludes
        return self._set("_source", spec)

    def highlight(self, *fields: str, **options: Any) -> QueryBuilder:
        return self._set("highlight", {"fields": {f: {} for f in fields}, **options})

    def collapse(self, field: str) -> QueryBuilder:
        return self._set("collapse", {"field": field})

    def track_total_hits(self, value: bool | int = True) -> QueryBuilder:
        return self._set("track_total_hits", value)

    def agg(self, name: str, agg: Agg | dict[str, Any]) -> QueryBuilder:
        clone = self._clone()
        body = agg.to_dict() if isinstance(agg, Agg) else copy.deepcopy(agg)
        clone._body.setdefault("aggs", {})[name] = body
        return clone

    def option(self, key: str, value: Any) -> QueryBuilder:
        """Set any other top-level search key (knn, post_filter, min_score, ...)."""
        return self._set(key, value)

    # ---- output ----
    def query_dict(self) -> dict[str, Any]:
        if not self._clauses:
            return {"match_all": {}}
        body: dict[str, Any] = copy.deepcopy(self._clauses)
        if self._msm is not None:
            body["minimum_should_match"] = self._msm
        return {"bool": body}

    def to_dict(self) -> dict[str, Any]:
        body = copy.deepcopy(self._body)
        # A pure kNN search must not get an implicit match_all added to it.
        if self._clauses or "knn" not in body:
            body["query"] = self.query_dict()
        return body

    def to_search(self, index: str | None = None, using: Any = "default") -> Any:
        """Convert to an elasticsearch.dsl Search. For async use to_async_search()."""
        from elasticsearch.dsl import Search

        return self._bind(Search, index, using)

    def to_async_search(self, index: str | None = None, using: Any = "default") -> Any:
        from elasticsearch.dsl import AsyncSearch

        return self._bind(AsyncSearch, index, using)

    def _bind(self, cls: Any, index: str | None, using: Any) -> Any:
        search = cls.from_dict(self.to_dict()).using(using)
        return search.index(index) if index else search
