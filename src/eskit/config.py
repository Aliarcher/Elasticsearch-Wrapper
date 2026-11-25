"""Connection settings, from code or environment variables."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from .exceptions import ESConfigError

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}


@dataclass(frozen=True)
class ESSettings:
    hosts: tuple[str, ...] = ()
    cloud_id: str | None = None
    api_key: str | None = field(default=None, repr=False)
    username: str | None = None
    password: str | None = field(default=None, repr=False)
    bearer_token: str | None = field(default=None, repr=False)
    verify_certs: bool = True
    ca_certs: str | None = None
    ssl_fingerprint: str | None = None
    request_timeout: float = 10.0
    max_retries: int = 3
    # Off by default: retrying a timed-out write may apply it twice.
    retry_on_timeout: bool = False
    http_compress: bool = True
    extra: Mapping[str, Any] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        if isinstance(self.hosts, str):
            object.__setattr__(self, "hosts", (self.hosts,))
        if bool(self.hosts) == bool(self.cloud_id):
            raise ESConfigError("Set exactly one of `hosts` or `cloud_id`.")
        if bool(self.username) != bool(self.password):
            raise ESConfigError("`username` and `password` must be set together.")
        methods = [self.api_key, self.username, self.bearer_token]
        if sum(bool(m) for m in methods) > 1:
            raise ESConfigError("Use only one authentication method.")

    def client_kwargs(self) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "request_timeout": self.request_timeout,
            "max_retries": self.max_retries,
            "retry_on_timeout": self.retry_on_timeout,
            "http_compress": self.http_compress,
        }
        if self.cloud_id:
            kwargs["cloud_id"] = self.cloud_id
        else:
            kwargs["hosts"] = list(self.hosts)
        if self.api_key:
            kwargs["api_key"] = self.api_key
        elif self.username:
            kwargs["basic_auth"] = (self.username, self.password)
        elif self.bearer_token:
            kwargs["bearer_auth"] = self.bearer_token
        # TLS options are only sent when set, so plain http:// hosts keep working.
        if not self.verify_certs:
            kwargs["verify_certs"] = False
        if self.ca_certs:
            kwargs["ca_certs"] = self.ca_certs
        if self.ssl_fingerprint:
            kwargs["ssl_assert_fingerprint"] = self.ssl_fingerprint
        kwargs.update(self.extra)
        return kwargs

    @classmethod
    def from_env(cls, prefix: str = "ES_", environ: Mapping[str, str] | None = None) -> ESSettings:
        env = os.environ if environ is None else environ

        def get(name: str) -> str | None:
            return env.get(prefix + name, "").strip() or None

        def flag(name: str, default: bool) -> bool:
            raw = get(name)
            if raw is None:
                return default
            if raw.lower() in _TRUE:
                return True
            if raw.lower() in _FALSE:
                return False
            raise ESConfigError(f"{prefix}{name} must be a boolean, got {raw!r}")

        def number(name: str, kind: type, default: Any) -> Any:
            raw = get(name)
            try:
                return default if raw is None else kind(raw)
            except ValueError as exc:
                raise ESConfigError(f"{prefix}{name} must be a number, got {raw!r}") from exc

        cloud_id = get("CLOUD_ID")
        raw_hosts = get("HOSTS") or ("" if cloud_id else "http://localhost:9200")
        return cls(
            hosts=tuple(h.strip() for h in raw_hosts.split(",") if h.strip()),
            cloud_id=cloud_id,
            api_key=get("API_KEY"),
            username=get("USERNAME"),
            password=get("PASSWORD"),
            bearer_token=get("BEARER_TOKEN"),
            verify_certs=flag("VERIFY_CERTS", True),
            ca_certs=get("CA_CERTS"),
            ssl_fingerprint=get("SSL_FINGERPRINT"),
            request_timeout=number("REQUEST_TIMEOUT", float, 10.0),
            max_retries=number("MAX_RETRIES", int, 3),
            retry_on_timeout=flag("RETRY_ON_TIMEOUT", False),
            http_compress=flag("HTTP_COMPRESS", True),
        )
