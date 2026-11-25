"""Optional base classes for elasticsearch.dsl Document models.

Import explicitly: `from eskit.documents import TimestampedDocument`.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from elasticsearch.dsl import AsyncDocument, Date, Document


def _now() -> datetime:
    return datetime.now(timezone.utc)


class TimestampedDocument(Document):
    created_at = Date()
    updated_at = Date()

    def save(self, **kwargs: Any) -> Any:
        self.updated_at = _now()
        self.created_at = self.created_at or self.updated_at
        return super().save(**kwargs)


class AsyncTimestampedDocument(AsyncDocument):
    created_at = Date()
    updated_at = Date()

    async def save(self, **kwargs: Any) -> Any:
        self.updated_at = _now()
        self.created_at = self.created_at or self.updated_at
        return await super().save(**kwargs)
