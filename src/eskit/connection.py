"""Lazy, thread-safe client management for one or more clusters."""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

from .config import ESSettings
from .exceptions import ESConfigError, translate_errors

ClientFactory = Callable[..., Any]


class _BaseManager:
    def __init__(self, factory: ClientFactory | None = None, register_dsl: bool = True) -> None:
        self._factory = factory
        # A custom factory (tests, fakes) is never registered with the DSL.
        self._register_dsl = register_dsl and factory is None
        self._settings: dict[str, ESSettings] = {}
        self._clients: dict[str, Any] = {}
        self._lock = threading.Lock()

    def configure(self, settings: ESSettings | None = None, alias: str = "default") -> None:
        """Register a cluster. No network traffic happens here."""
        if alias in self._clients:
            raise ESConfigError(f"Connection {alias!r} is already open; close it first.")
        self._settings[alias] = settings or ESSettings.from_env()

    def client(self, alias: str = "default") -> Any:
        """Return the client for `alias`, creating it on first use."""
        with self._lock:
            if alias not in self._clients:
                if alias not in self._settings:
                    raise ESConfigError(f"Connection {alias!r} is not configured.")
                factory = self._factory or self._default_factory()
                client = factory(**self._settings[alias].client_kwargs())
                if self._register_dsl:
                    self._dsl_connections().add_connection(alias, client)
                self._clients[alias] = client
            return self._clients[alias]

    def _pop_all(self) -> list[Any]:
        with self._lock:
            if self._register_dsl:
                for alias in self._clients:
                    self._dsl_connections().remove_connection(alias)
            clients = list(self._clients.values())
            self._clients.clear()
            return clients

    def _default_factory(self) -> ClientFactory:
        raise NotImplementedError

    def _dsl_connections(self) -> Any:
        raise NotImplementedError


class ESManager(_BaseManager):
    def _default_factory(self) -> ClientFactory:
        from elasticsearch import Elasticsearch

        return Elasticsearch

    def _dsl_connections(self) -> Any:
        from elasticsearch.dsl import connections

        return connections

    def ping(self, alias: str = "default") -> bool:
        return bool(self.client(alias).ping())

    def health(self, alias: str = "default") -> dict[str, Any]:
        with translate_errors():
            return dict(self.client(alias).cluster.health())

    def close(self) -> None:
        for client in self._pop_all():
            client.close()

    def __enter__(self) -> ESManager:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


class AsyncESManager(_BaseManager):
    def _default_factory(self) -> ClientFactory:
        from elasticsearch import AsyncElasticsearch

        return AsyncElasticsearch

    def _dsl_connections(self) -> Any:
        from elasticsearch.dsl import async_connections

        return async_connections

    async def ping(self, alias: str = "default") -> bool:
        return bool(await self.client(alias).ping())

    async def health(self, alias: str = "default") -> dict[str, Any]:
        with translate_errors():
            return dict(await self.client(alias).cluster.health())

    async def close(self) -> None:
        for client in self._pop_all():
            await client.close()

    async def __aenter__(self) -> AsyncESManager:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()
