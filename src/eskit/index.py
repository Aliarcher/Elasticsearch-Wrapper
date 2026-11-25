"""Index management, including alias-based reindexing without read downtime."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .exceptions import ESConfigError, ESKitError, translate_errors


def versioned_name(alias: str) -> str:
    return f"{alias}-{datetime.now(timezone.utc):%Y%m%d%H%M%S%f}"


def _guard(name: str) -> None:
    if not name or name == "_all" or "*" in name or "," in name:
        raise ESConfigError(f"Refusing to delete {name!r}: pass one exact index name.")


def _create_args(
    mappings: dict[str, Any] | None,
    settings: dict[str, Any] | None,
    aliases: dict[str, Any] | None,
) -> dict[str, Any]:
    args = {"mappings": mappings, "settings": settings, "aliases": aliases}
    return {k: v for k, v in args.items() if v is not None}


def _swap_actions(alias: str, old: list[str], new: str) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = [{"remove": {"index": i, "alias": alias}} for i in old]
    actions.append({"add": {"index": new, "alias": alias, "is_write_index": True}})
    return actions


def _check_reindex(response: Any) -> None:
    if response.get("failures") or response.get("timed_out"):
        raise ESKitError("Reindex failed; the alias was not changed.", body=dict(response))


class IndexManager:
    def __init__(self, client: Any) -> None:
        self.client = client

    def exists(self, index: str) -> bool:
        with translate_errors():
            return bool(self.client.indices.exists(index=index))

    def create(
        self,
        index: str,
        *,
        mappings: dict[str, Any] | None = None,
        settings: dict[str, Any] | None = None,
        aliases: dict[str, Any] | None = None,
    ) -> None:
        with translate_errors():
            self.client.indices.create(index=index, **_create_args(mappings, settings, aliases))

    def ensure(self, index: str, **definition: Any) -> bool:
        """Create if missing. Returns True when it was created."""
        if self.exists(index):
            return False
        try:
            self.create(index, **definition)
        except ESKitError as exc:
            if "resource_already_exists_exception" in str(exc.body):
                return False  # another process created it first
            raise
        return True

    def delete(self, index: str) -> None:
        _guard(index)
        with translate_errors():
            self.client.indices.delete(index=index)

    def refresh(self, index: str) -> None:
        with translate_errors():
            self.client.indices.refresh(index=index)

    def add_fields(self, index: str, properties: dict[str, Any]) -> None:
        with translate_errors():
            self.client.indices.put_mapping(index=index, properties=properties)

    def aliased_indices(self, alias: str) -> list[str]:
        with translate_errors():
            if not self.client.indices.exists_alias(name=alias):
                return []
            return list(self.client.indices.get_alias(name=alias).keys())

    def migrate(
        self,
        alias: str,
        *,
        mappings: dict[str, Any] | None = None,
        settings: dict[str, Any] | None = None,
        timeout: float = 3600,
    ) -> str:
        """Create a new versioned index, copy data, then atomically move the alias.

        Reads keep working. Pause writes meanwhile: documents written to the old
        index during the copy may be missing from the new one. Old indices are kept.
        """
        old = self.aliased_indices(alias)
        if not old and self.exists(alias):
            raise ESConfigError(f"{alias!r} is a real index, not an alias.")
        new = versioned_name(alias)
        self.create(new, mappings=mappings, settings=settings)
        try:
            if old:
                with translate_errors():
                    response = self.client.options(request_timeout=timeout).reindex(
                        source={"index": alias},
                        dest={"index": new},
                        wait_for_completion=True,
                        refresh=True,
                    )
                _check_reindex(response)
            with translate_errors():
                self.client.indices.update_aliases(actions=_swap_actions(alias, old, new))
        except ESKitError as exc:
            # After a network error the outcome is unknown, so keep the new index.
            if exc.status is not None or exc.body is not None:
                self.delete(new)
            raise
        return new


class AsyncIndexManager:
    def __init__(self, client: Any) -> None:
        self.client = client

    async def exists(self, index: str) -> bool:
        with translate_errors():
            return bool(await self.client.indices.exists(index=index))

    async def create(
        self,
        index: str,
        *,
        mappings: dict[str, Any] | None = None,
        settings: dict[str, Any] | None = None,
        aliases: dict[str, Any] | None = None,
    ) -> None:
        with translate_errors():
            await self.client.indices.create(
                index=index, **_create_args(mappings, settings, aliases)
            )

    async def ensure(self, index: str, **definition: Any) -> bool:
        if await self.exists(index):
            return False
        try:
            await self.create(index, **definition)
        except ESKitError as exc:
            if "resource_already_exists_exception" in str(exc.body):
                return False
            raise
        return True

    async def delete(self, index: str) -> None:
        _guard(index)
        with translate_errors():
            await self.client.indices.delete(index=index)

    async def refresh(self, index: str) -> None:
        with translate_errors():
            await self.client.indices.refresh(index=index)

    async def add_fields(self, index: str, properties: dict[str, Any]) -> None:
        with translate_errors():
            await self.client.indices.put_mapping(index=index, properties=properties)

    async def aliased_indices(self, alias: str) -> list[str]:
        with translate_errors():
            if not await self.client.indices.exists_alias(name=alias):
                return []
            response = await self.client.indices.get_alias(name=alias)
        return list(response.keys())

    async def migrate(
        self,
        alias: str,
        *,
        mappings: dict[str, Any] | None = None,
        settings: dict[str, Any] | None = None,
        timeout: float = 3600,
    ) -> str:
        """Async version of IndexManager.migrate (same caveats)."""
        old = await self.aliased_indices(alias)
        if not old and await self.exists(alias):
            raise ESConfigError(f"{alias!r} is a real index, not an alias.")
        new = versioned_name(alias)
        await self.create(new, mappings=mappings, settings=settings)
        try:
            if old:
                with translate_errors():
                    response = await self.client.options(request_timeout=timeout).reindex(
                        source={"index": alias},
                        dest={"index": new},
                        wait_for_completion=True,
                        refresh=True,
                    )
                _check_reindex(response)
            with translate_errors():
                await self.client.indices.update_aliases(actions=_swap_actions(alias, old, new))
        except ESKitError as exc:
            if exc.status is not None or exc.body is not None:
                await self.delete(new)
            raise
        return new
