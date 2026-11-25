"""One exception hierarchy for everything that can go wrong."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any


class ESKitError(Exception):
    """Base class. `status` and `body` are filled for HTTP errors."""

    def __init__(self, message: str, *, status: int | None = None, body: Any = None) -> None:
        super().__init__(message)
        self.status = status
        self.body = body


class ESConfigError(ESKitError):
    pass


class ESConnectionError(ESKitError):
    pass


class ESTimeoutError(ESConnectionError):
    pass


class ESAuthError(ESKitError):
    pass


class ESNotFoundError(ESKitError):
    pass


class ESConflictError(ESKitError):
    pass


class ESQueryError(ESKitError):
    pass


class ESBulkError(ESKitError):
    pass


class ESReadOnlyError(ESKitError):
    """A write was attempted through a read-only object."""


_BY_STATUS: dict[int, type[ESKitError]] = {
    400: ESQueryError,
    401: ESAuthError,
    403: ESAuthError,
    404: ESNotFoundError,
    409: ESConflictError,
}


def translate(exc: Exception) -> ESKitError | None:
    """Map a client exception to ours. Returns None for unrelated exceptions."""
    root = type(exc).__module__.split(".")[0]
    if root not in {"elasticsearch", "elastic_transport"}:
        return None
    names = {cls.__name__ for cls in type(exc).__mro__}
    status = getattr(getattr(exc, "meta", None), "status", None)
    body = getattr(exc, "body", None)
    if "ConnectionTimeout" in names:
        kind: type[ESKitError] = ESTimeoutError
    elif "ConnectionError" in names:
        kind = ESConnectionError
    else:
        kind = _BY_STATUS.get(status or 0, ESKitError)
    return kind(str(exc), status=status, body=body)


@contextmanager
def translate_errors() -> Iterator[None]:
    """Works around both sync and `await` calls."""
    try:
        yield
    except Exception as exc:
        converted = translate(exc)
        if converted is None:
            raise
        raise converted from exc
