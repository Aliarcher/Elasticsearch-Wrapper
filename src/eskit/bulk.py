"""Bulk writes with a clear report."""

from __future__ import annotations

from collections.abc import AsyncIterable, Iterable
from dataclasses import dataclass, field
from typing import Any

from .exceptions import ESBulkError, translate_errors

MAX_KEPT_ERRORS = 100


@dataclass
class BulkReport:
    succeeded: int = 0
    failed: int = 0
    errors: list[dict[str, Any]] = field(default_factory=list)  # first 100 only

    def add(self, ok: bool, item: dict[str, Any]) -> None:
        if ok:
            self.succeeded += 1
            return
        self.failed += 1
        if len(self.errors) < MAX_KEPT_ERRORS:
            self.errors.append(item)

    def raise_for_errors(self) -> BulkReport:
        if self.failed:
            raise ESBulkError(f"{self.failed} bulk operations failed", body=self.errors)
        return self


def _options(chunk_size: int, max_retries: int, refresh: Any) -> dict[str, Any]:
    options: dict[str, Any] = {
        "chunk_size": chunk_size,
        "max_retries": max_retries,  # retries documents rejected with HTTP 429
        "raise_on_error": False,
    }
    if refresh is not None:
        options["refresh"] = refresh
    return options


def bulk_write(
    client: Any,
    actions: Iterable[dict[str, Any]],
    *,
    chunk_size: int = 500,
    max_retries: int = 3,
    refresh: bool | str | None = None,
) -> BulkReport:
    """Stream actions to the bulk API. Failed documents are reported, not raised."""
    from elasticsearch.helpers import streaming_bulk

    report = BulkReport()
    with translate_errors():
        for ok, item in streaming_bulk(
            client, actions, **_options(chunk_size, max_retries, refresh)
        ):
            report.add(ok, item)
    return report


async def abulk_write(
    client: Any,
    actions: Iterable[dict[str, Any]] | AsyncIterable[dict[str, Any]],
    *,
    chunk_size: int = 500,
    max_retries: int = 3,
    refresh: bool | str | None = None,
) -> BulkReport:
    from elasticsearch.helpers import async_streaming_bulk

    report = BulkReport()
    with translate_errors():
        async for ok, item in async_streaming_bulk(
            client, actions, **_options(chunk_size, max_retries, refresh)
        ):
            report.add(ok, item)
    return report
