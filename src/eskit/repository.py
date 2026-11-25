"""Repository pattern: CRUD, search, bulk and deep iteration for one index."""

from __future__ import annotations

import dataclasses
from collections.abc import AsyncIterator, Iterable, Iterator, Mapping
from typing import Any, Generic, TypeVar

from .bulk import BulkReport, abulk_write, bulk_write
from .exceptions import ESNotFoundError, translate_errors
from .query import QueryBuilder
from .results import Hit, SearchResult

T = TypeVar("T")
Refresh = bool | str | None


def _opts(**values: Any) -> dict[str, Any]:
    return {k: v for k, v in values.items() if v is not None}


def _is_missing_document(exc: ESNotFoundError) -> bool:
    """True for a missing document, False for e.g. a missing index."""
    return isinstance(exc.body, Mapping) and "error" not in exc.body


class _BaseRepository(Generic[T]):
    index: str = ""
    model: type | None = None  # dataclass or pydantic model; None means plain dicts
    id_field: str = "id"

    def __init__(
        self,
        client: Any,
        index: str | None = None,
        model: type[T] | None = None,
    ) -> None:
        self.client = client
        self.index = index or type(self).index
        self.model = model or type(self).model
        if not self.index:
            raise ValueError("Repository needs an index name.")

    # ---- serialization (override for custom needs) ----
    def dump(self, entity: Any) -> dict[str, Any]:
        if isinstance(entity, Mapping):
            return dict(entity)
        if hasattr(entity, "model_dump"):
            return entity.model_dump(mode="json")
        if dataclasses.is_dataclass(entity) and not isinstance(entity, type):
            return dataclasses.asdict(entity)
        raise TypeError(f"Cannot serialize {type(entity).__name__}")

    def load(self, source: dict[str, Any], doc_id: str) -> T:
        if self.model is None:
            return {**source, self.id_field: doc_id}  # type: ignore[return-value]
        data = dict(source)
        fields = getattr(self.model, "model_fields", None) or getattr(
            self.model, "__dataclass_fields__", {}
        )
        if self.id_field in fields:
            data[self.id_field] = doc_id
        return self.model(**data)

    def _prepare(self, entity: Any, doc_id: str | None) -> tuple[str | None, dict[str, Any]]:
        """Split an entity into (_id, _source). The id is not stored in _source."""
        source = self.dump(entity)
        own_id = source.pop(self.id_field, None)
        if doc_id is None and own_id is not None:
            doc_id = str(own_id)
        return doc_id, source

    def _actions(self, entity: Any) -> dict[str, Any]:
        doc_id, source = self._prepare(entity, None)
        action = {"_op_type": "index", "_index": self.index, "_source": source}
        if doc_id is not None:
            action["_id"] = doc_id
        return action

    @staticmethod
    def _body(query: QueryBuilder | None) -> dict[str, Any]:
        return (query or QueryBuilder()).to_dict()

    def _pit_body(
        self, query: QueryBuilder | None, batch_size: int, pit_id: str, keep_alive: str
    ) -> dict[str, Any]:
        body = self._body(query)
        for key in ("from", "search_after"):
            body.pop(key, None)
        body["size"] = batch_size
        body["pit"] = {"id": pit_id, "keep_alive": keep_alive}
        body.setdefault("sort", ["_shard_doc"])
        body["track_total_hits"] = False
        return body


class Repository(_BaseRepository[T]):
    def get(self, doc_id: str) -> T:
        with translate_errors():
            response = self.client.get(index=self.index, id=doc_id)
        return self.load(response["_source"], response["_id"])

    def find(self, doc_id: str) -> T | None:
        try:
            return self.get(doc_id)
        except ESNotFoundError as exc:
            if _is_missing_document(exc):
                return None
            raise

    def get_many(self, ids: Iterable[str]) -> list[T]:
        wanted = list(ids)
        if not wanted:
            return []
        with translate_errors():
            response = self.client.mget(index=self.index, ids=wanted)
        return self._found(response)

    def _found(self, response: Mapping[str, Any]) -> list[T]:
        for doc in response["docs"]:
            if "error" in doc:
                raise ESNotFoundError(f"mget failed: {doc['error']}", body=doc)
        return [self.load(d["_source"], d["_id"]) for d in response["docs"] if d.get("found")]

    def exists(self, doc_id: str) -> bool:
        with translate_errors():
            return bool(self.client.exists(index=self.index, id=doc_id))

    def save(self, entity: Any, doc_id: str | None = None, *, refresh: Refresh = None) -> str:
        """Create or fully replace. Returns the document id."""
        doc_id, source = self._prepare(entity, doc_id)
        with translate_errors():
            response = self.client.index(
                index=self.index, document=source, **_opts(id=doc_id, refresh=refresh)
            )
        return response["_id"]

    def create(self, entity: Any, doc_id: str | None = None, *, refresh: Refresh = None) -> str:
        """Create only. Raises ESConflictError if the id exists."""
        doc_id, source = self._prepare(entity, doc_id)
        with translate_errors():
            response = self.client.index(
                index=self.index,
                document=source,
                op_type="create",
                **_opts(id=doc_id, refresh=refresh),
            )
        return response["_id"]

    def update(
        self,
        doc_id: str,
        changes: Mapping[str, Any],
        *,
        upsert: bool = False,
        refresh: Refresh = None,
        retry_on_conflict: int = 3,
    ) -> None:
        """Partial update."""
        with translate_errors():
            self.client.update(
                index=self.index,
                id=doc_id,
                doc=dict(changes),
                doc_as_upsert=upsert,
                retry_on_conflict=retry_on_conflict,
                **_opts(refresh=refresh),
            )

    def delete(self, doc_id: str, *, refresh: Refresh = None) -> bool:
        """Returns False if the document did not exist."""
        try:
            with translate_errors():
                self.client.delete(index=self.index, id=doc_id, **_opts(refresh=refresh))
        except ESNotFoundError as exc:
            if _is_missing_document(exc):
                return False
            raise
        return True

    def search(self, query: QueryBuilder | None = None) -> SearchResult[T]:
        with translate_errors():
            response = self.client.search(index=self.index, body=self._body(query))
        return SearchResult.from_response(response, self.load)

    def first(self, query: QueryBuilder | None = None) -> T | None:
        result = self.search((query or QueryBuilder()).size(1))
        return result.items[0] if result.hits else None

    def count(self, query: QueryBuilder | None = None) -> int:
        body = {"query": (query or QueryBuilder()).query_dict()}
        with translate_errors():
            return self.client.count(index=self.index, body=body)["count"]

    def iter_all(
        self,
        query: QueryBuilder | None = None,
        *,
        batch_size: int = 1000,
        keep_alive: str = "2m",
    ) -> Iterator[Hit[T]]:
        """Walk every match using point-in-time + search_after (no 10k limit)."""
        with translate_errors():
            pit_id = self.client.open_point_in_time(index=self.index, keep_alive=keep_alive)["id"]
        try:
            after = None
            while True:
                body = self._pit_body(query, batch_size, pit_id, keep_alive)
                if after is not None:
                    body["search_after"] = after
                with translate_errors():
                    response = self.client.search(body=body, allow_partial_search_results=False)
                pit_id = response.get("pit_id", pit_id)
                result = SearchResult.from_response(response, self.load)
                if not result.hits:
                    return
                yield from result.hits
                after = result.next_search_after
        finally:
            with translate_errors():
                self.client.close_point_in_time(id=pit_id)

    def bulk_save(self, entities: Iterable[Any], **options: Any) -> BulkReport:
        return bulk_write(self.client, (self._actions(e) for e in entities), **options)


class AsyncRepository(_BaseRepository[T]):
    async def get(self, doc_id: str) -> T:
        with translate_errors():
            response = await self.client.get(index=self.index, id=doc_id)
        return self.load(response["_source"], response["_id"])

    async def find(self, doc_id: str) -> T | None:
        try:
            return await self.get(doc_id)
        except ESNotFoundError as exc:
            if _is_missing_document(exc):
                return None
            raise

    async def get_many(self, ids: Iterable[str]) -> list[T]:
        wanted = list(ids)
        if not wanted:
            return []
        with translate_errors():
            response = await self.client.mget(index=self.index, ids=wanted)
        for doc in response["docs"]:
            if "error" in doc:
                raise ESNotFoundError(f"mget failed: {doc['error']}", body=doc)
        return [self.load(d["_source"], d["_id"]) for d in response["docs"] if d.get("found")]

    async def exists(self, doc_id: str) -> bool:
        with translate_errors():
            return bool(await self.client.exists(index=self.index, id=doc_id))

    async def save(
        self, entity: Any, doc_id: str | None = None, *, refresh: Refresh = None
    ) -> str:
        doc_id, source = self._prepare(entity, doc_id)
        with translate_errors():
            response = await self.client.index(
                index=self.index, document=source, **_opts(id=doc_id, refresh=refresh)
            )
        return response["_id"]

    async def create(
        self, entity: Any, doc_id: str | None = None, *, refresh: Refresh = None
    ) -> str:
        doc_id, source = self._prepare(entity, doc_id)
        with translate_errors():
            response = await self.client.index(
                index=self.index,
                document=source,
                op_type="create",
                **_opts(id=doc_id, refresh=refresh),
            )
        return response["_id"]

    async def update(
        self,
        doc_id: str,
        changes: Mapping[str, Any],
        *,
        upsert: bool = False,
        refresh: Refresh = None,
        retry_on_conflict: int = 3,
    ) -> None:
        with translate_errors():
            await self.client.update(
                index=self.index,
                id=doc_id,
                doc=dict(changes),
                doc_as_upsert=upsert,
                retry_on_conflict=retry_on_conflict,
                **_opts(refresh=refresh),
            )

    async def delete(self, doc_id: str, *, refresh: Refresh = None) -> bool:
        try:
            with translate_errors():
                await self.client.delete(index=self.index, id=doc_id, **_opts(refresh=refresh))
        except ESNotFoundError as exc:
            if _is_missing_document(exc):
                return False
            raise
        return True

    async def search(self, query: QueryBuilder | None = None) -> SearchResult[T]:
        with translate_errors():
            response = await self.client.search(index=self.index, body=self._body(query))
        return SearchResult.from_response(response, self.load)

    async def first(self, query: QueryBuilder | None = None) -> T | None:
        result = await self.search((query or QueryBuilder()).size(1))
        return result.items[0] if result.hits else None

    async def count(self, query: QueryBuilder | None = None) -> int:
        body = {"query": (query or QueryBuilder()).query_dict()}
        with translate_errors():
            response = await self.client.count(index=self.index, body=body)
        return response["count"]

    async def iter_all(
        self,
        query: QueryBuilder | None = None,
        *,
        batch_size: int = 1000,
        keep_alive: str = "2m",
    ) -> AsyncIterator[Hit[T]]:
        """If you stop early, wrap in contextlib.aclosing() to release the PIT at once."""
        with translate_errors():
            opened = await self.client.open_point_in_time(index=self.index, keep_alive=keep_alive)
        pit_id = opened["id"]
        try:
            after = None
            while True:
                body = self._pit_body(query, batch_size, pit_id, keep_alive)
                if after is not None:
                    body["search_after"] = after
                with translate_errors():
                    response = await self.client.search(
                        body=body, allow_partial_search_results=False
                    )
                pit_id = response.get("pit_id", pit_id)
                result = SearchResult.from_response(response, self.load)
                if not result.hits:
                    return
                for hit in result.hits:
                    yield hit
                after = result.next_search_after
        finally:
            with translate_errors():
                await self.client.close_point_in_time(id=pit_id)

    async def bulk_save(self, entities: Iterable[Any], **options: Any) -> BulkReport:
        return await abulk_write(self.client, (self._actions(e) for e in entities), **options)
