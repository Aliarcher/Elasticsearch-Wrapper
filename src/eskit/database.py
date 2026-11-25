"""Entry point for working with a cluster that already holds data."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, TypeVar

from .exceptions import ESConfigError, ESKitError, translate_errors
from .repository import AsyncRepository, Repository
from .schema import Schema

T = TypeVar("T")

_CAT_COLUMNS = "index,health,status,docs.count,store.size"


@dataclass(frozen=True)
class ServerInfo:
    cluster_name: str
    version: str

    @property
    def major(self) -> int:
        return int(self.version.split(".")[0])


@dataclass(frozen=True)
class IndexInfo:
    name: str
    health: str | None
    status: str | None
    docs: int | None
    size: str | None


def client_major() -> int | None:
    try:
        from elasticsearch import __versionstr__
    except ImportError:
        return None
    return int(__versionstr__.split(".")[0])


def _server_info(response: Mapping[str, Any]) -> ServerInfo:
    info = ServerInfo(response["cluster_name"], response["version"]["number"])
    installed = client_major()
    if installed is not None and installed != info.major:
        raise ESConfigError(_mismatch(installed, info.version))
    return info


def _mismatch(installed: int | None, server: str) -> str:
    return (
        f"Client major version ({installed}) does not match the server ({server}). "
        "Install the matching client, e.g. pip install 'elasticsearch>=8.18,<9' for 8.x. "
        "Servers older than 8 are not supported."
    )


def _explain(exc: ESKitError) -> ESKitError:
    text = f"{exc} {exc.body}"
    if "media_type_header_exception" in text or "compatible-with" in text:
        return ESConfigError(_mismatch(client_major(), "different major"), body=exc.body)
    return exc


def _indices(rows: Any, include_hidden: bool) -> list[IndexInfo]:
    result = [
        IndexInfo(
            name=r["index"],
            health=r.get("health"),
            status=r.get("status"),
            docs=int(r["docs.count"]) if r.get("docs.count") else None,
            size=r.get("store.size"),
        )
        for r in rows
        if include_hidden or not r["index"].startswith(".")
    ]
    return sorted(result, key=lambda i: i.name)


class Database:
    """Read-only by default. Pass read_only=False to allow writes.

    The flag only guards eskit repositories against mistakes. For real protection
    connect with an API key or user that has read privileges only.
    """

    def __init__(self, client: Any, *, read_only: bool = True) -> None:
        self.client = client
        self.read_only = read_only

    def check(self) -> ServerInfo:
        """Verify connection, credentials and version compatibility."""
        try:
            with translate_errors():
                response = self.client.info()
        except ESKitError as exc:
            raise _explain(exc) from exc
        return _server_info(response)

    def indices(self, pattern: str = "*", *, include_hidden: bool = False) -> list[IndexInfo]:
        """Needs the `monitor` index privilege."""
        with translate_errors():
            rows = self.client.cat.indices(index=pattern, format="json", h=_CAT_COLUMNS)
        return _indices(rows, include_hidden)

    def schema(self, index: str) -> Schema:
        """Needs the `view_index_metadata` privilege."""
        with translate_errors():
            response = self.client.indices.get_mapping(index=index)
        return Schema.from_mapping(response)

    def repository(
        self, index: str, model: type[T] | None = None, *, id_field: str | None = None
    ) -> Repository[T]:
        """`index` may be an index, alias, data stream or pattern such as "logs-*".

        get/save/update/delete need one concrete target; search, count and
        iter_all also work with patterns.
        """
        repo: Repository[T] = Repository(
            self.client, index=index, model=model, read_only=self.read_only
        )
        if id_field:
            repo.id_field = id_field
        return repo


class AsyncDatabase:
    """Async version of Database."""

    def __init__(self, client: Any, *, read_only: bool = True) -> None:
        self.client = client
        self.read_only = read_only

    async def check(self) -> ServerInfo:
        try:
            with translate_errors():
                response = await self.client.info()
        except ESKitError as exc:
            raise _explain(exc) from exc
        return _server_info(response)

    async def indices(
        self, pattern: str = "*", *, include_hidden: bool = False
    ) -> list[IndexInfo]:
        with translate_errors():
            rows = await self.client.cat.indices(index=pattern, format="json", h=_CAT_COLUMNS)
        return _indices(rows, include_hidden)

    async def schema(self, index: str) -> Schema:
        with translate_errors():
            response = await self.client.indices.get_mapping(index=index)
        return Schema.from_mapping(response)

    def repository(
        self, index: str, model: type[T] | None = None, *, id_field: str | None = None
    ) -> AsyncRepository[T]:
        repo: AsyncRepository[T] = AsyncRepository(
            self.client, index=index, model=model, read_only=self.read_only
        )
        if id_field:
            repo.id_field = id_field
        return repo
