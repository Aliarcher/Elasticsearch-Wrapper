from dataclasses import dataclass

import pytest
from conftest import make_error, search_response

from eskit import (
    ESBulkError, ESConflictError, ESNotFoundError, ESTimeoutError, F, QueryBuilder, Repository,
)


@dataclass
class Item:
    id: str
    name: str


def repo(client):
    return Repository(client, index="items", model=Item)


def test_save_does_not_store_id_in_source(client):
    client.index.return_value = {"_id": "7"}
    assert repo(client).save(Item("7", "n"), refresh=False) == "7"
    client.index.assert_called_once_with(
        index="items", document={"name": "n"}, id="7", refresh=False
    )


def test_get_loads_model(client):
    client.get.return_value = {"_id": "1", "_source": {"name": "a"}}
    assert repo(client).get("1") == Item("1", "a")


def test_find_missing_document_vs_missing_index(client):
    client.get.side_effect = make_error("NotFoundError", 404, {"found": False})
    assert repo(client).find("1") is None
    client.get.side_effect = make_error("NotFoundError", 404, {"error": {"type": "index"}})
    with pytest.raises(ESNotFoundError):
        repo(client).find("1")


def test_delete_missing(client):
    client.delete.side_effect = make_error("NotFoundError", 404, {"result": "not_found"})
    assert repo(client).delete("1") is False


@pytest.mark.parametrize(
    "error, expected",
    [
        (make_error("ConflictError", 409, {}), ESConflictError),
        (make_error("ConnectionTimeout"), ESTimeoutError),
    ],
)
def test_error_translation(client, error, expected):
    client.index.side_effect = error
    with pytest.raises(expected) as info:
        repo(client).create(Item("1", "a"))
    assert info.value.__cause__ is error


def test_unrelated_errors_pass_through(client):
    client.get.side_effect = KeyError("boom")
    with pytest.raises(KeyError):
        repo(client).get("1")


def test_search_and_count(client):
    client.search.return_value = search_response(("1", {"name": "a"}))
    client.count.return_value = {"count": 5}
    query = QueryBuilder().filter(F("name") == "a").size(3)
    result = repo(client).search(query)
    assert result.items == [Item("1", "a")] and result.total == 1 and not result.is_partial
    assert repo(client).count(query) == 5
    assert set(client.count.call_args.kwargs["body"]) == {"query"}


def test_iter_all_pages_and_closes_pit(client):
    client.open_point_in_time.return_value = {"id": "p1"}
    client.search.side_effect = [
        {**search_response(("1", {"name": "a"})), "pit_id": "p2"},
        search_response(),
    ]
    assert [h.id for h in repo(client).iter_all(batch_size=1)] == ["1"]
    second = client.search.call_args_list[1].kwargs["body"]
    assert second["search_after"] == [0] and second["pit"]["id"] == "p2"
    assert "index" not in client.search.call_args_list[0].kwargs
    client.close_point_in_time.assert_called_once_with(id="p2")


def test_iter_all_closes_pit_on_error(client):
    client.open_point_in_time.return_value = {"id": "p"}
    client.search.side_effect = make_error("ApiError", 500, {})
    with pytest.raises(Exception):
        list(repo(client).iter_all())
    client.close_point_in_time.assert_called_once_with(id="p")


def test_bulk_report(client, fake_helpers):
    report = repo(client).bulk_save([Item("1", "a"), Item("bad", "b")], refresh="wait_for")
    assert (report.succeeded, report.failed) == (1, 1)
    assert fake_helpers["options"]["refresh"] == "wait_for"
    with pytest.raises(ESBulkError):
        report.raise_for_errors()
