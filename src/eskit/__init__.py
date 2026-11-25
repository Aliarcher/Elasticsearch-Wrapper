"""eskit: a friendly layer over elasticsearch-py and elasticsearch.dsl."""

from .bulk import BulkReport, abulk_write, bulk_write
from .config import ESSettings
from .connection import AsyncESManager, ESManager
from .exceptions import (
    ESAuthError,
    ESBulkError,
    ESConfigError,
    ESConflictError,
    ESConnectionError,
    ESKitError,
    ESNotFoundError,
    ESQueryError,
    ESTimeoutError,
)
from .index import AsyncIndexManager, IndexManager
from .query import Agg, F, QueryBuilder, Raw, match_all, multi_match, nested
from .repository import AsyncRepository, Repository
from .results import Hit, SearchResult

__all__ = [
    "Agg", "AsyncESManager", "AsyncIndexManager", "AsyncRepository", "BulkReport",
    "ESAuthError", "ESBulkError", "ESConfigError", "ESConflictError", "ESConnectionError",
    "ESKitError", "ESManager", "ESNotFoundError", "ESQueryError", "ESSettings",
    "ESTimeoutError", "F", "Hit", "IndexManager", "QueryBuilder", "Raw", "Repository",
    "SearchResult", "abulk_write", "bulk_write", "match_all", "multi_match", "nested",
]
