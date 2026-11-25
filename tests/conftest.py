"""Fakes so the tests run without a cluster."""

import sys
import types
from unittest.mock import MagicMock

import pytest


class _Meta:
    def __init__(self, status):
        self.status = status


def make_error(name, status=None, body=None):
    """An exception that looks like one raised by the real client."""
    cls = type(name, (Exception,), {"__module__": "elasticsearch.exceptions"})
    error = cls(name)
    if status is not None:
        error.meta = _Meta(status)
        error.body = body
    return error


def search_response(*docs):
    return {
        "took": 1,
        "timed_out": False,
        "_shards": {"failed": 0},
        "hits": {
            "total": {"value": len(docs), "relation": "eq"},
            "hits": [
                {"_id": i, "_index": "x", "_score": 1.0, "_source": src, "sort": [n]}
                for n, (i, src) in enumerate(docs)
            ],
        },
    }


@pytest.fixture
def client():
    return MagicMock()


@pytest.fixture
def fake_helpers(monkeypatch):
    calls = {}

    def streaming_bulk(client, actions, **options):
        calls["options"] = options
        for action in actions:
            yield action.get("_id") != "bad", {"index": action}

    root = types.ModuleType("elasticsearch")
    helpers = types.ModuleType("elasticsearch.helpers")
    helpers.streaming_bulk = streaming_bulk
    root.helpers = helpers
    monkeypatch.setitem(sys.modules, "elasticsearch", root)
    monkeypatch.setitem(sys.modules, "elasticsearch.helpers", helpers)
    return calls
