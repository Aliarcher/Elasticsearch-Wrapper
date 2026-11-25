from dataclasses import dataclass
from unittest.mock import MagicMock

import pytest
from conftest import make_error, search_response

from eskit import Database, ESConfigError, ESQueryError, ESReadOnlyError, Repository, Schema
from eskit import cli, database

MAPPING = {
    "a": {"mappings": {"properties": {
        "title": {"type": "text", "fields": {"keyword": {"type": "keyword"}}},
        "body": {"type": "text"},
        "price": {"type": "long"},
        "heading": {"type": "alias", "path": "body"},
        "comments": {"type": "nested", "properties": {"by": {"type": "keyword"}}},
        "user": {"properties": {"name": {"type": "keyword"}}},
    }}},
    "b": {"mappings": {"properties": {"price": {"type": "keyword"}}}},
}


def test_schema_resolves_fields():
    schema = Schema.from_mapping(MAPPING)
    assert schema.exact("title").name == "title.keyword"
    assert schema.text("title").name == "title"
    assert schema.exact("user.name").name == "user.name"
    assert schema.field("comments.by").nested_path == "comments"
    assert schema.text("heading").name == "heading"
    assert [f.name for f in schema.conflicts()] == ["price"]
    for bad in (lambda: schema.exact("body"), lambda: schema.text("price"),
                lambda: schema.field("nope")):
        with pytest.raises(ESQueryError):
            bad()


@pytest.mark.parametrize("method, args", [
    ("save", ({"a": 1},)), ("create", ({"a": 1},)), ("update", ("1", {})),
    ("delete", ("1",)), ("bulk_save", ([],)),
])
def test_database_is_read_only_by_default(client, method, args):
    repo = Database(client).repository("i")
    with pytest.raises(ESReadOnlyError):
        getattr(repo, method)(*args)
    assert client.method_calls == []


def test_writes_can_be_enabled(client):
    client.index.return_value = {"_id": "1"}
    Database(client, read_only=False).repository("i").save({"a": 1})
    client.index.assert_called_once()


def test_existing_id_field_is_preserved(client):
    client.index.return_value = {"_id": "es1"}
    repo = Repository(client, index="i")
    loaded = repo.load({"id": 42}, "es1")
    assert loaded == {"id": 42, "_id": "es1"}
    repo.save(loaded)
    client.index.assert_called_once_with(index="i", document={"id": 42}, id="es1")


def test_model_ignores_unknown_fields(client):
    @dataclass
    class Item:
        id: str
        name: str

    repo = Repository(client, index="i", model=Item)
    assert repo.load({"name": "n", "legacy": 1}, "x") == Item("x", "n")
    assert repo.load({"name": "n", "id": "own"}, "x") == Item("own", "n")


def info(version):
    return {"cluster_name": "c", "version": {"number": version}}


def test_check_version(client, monkeypatch):
    monkeypatch.setattr(database, "client_major", lambda: 9)
    client.info.return_value = info("9.1.0")
    assert Database(client).check().major == 9
    client.info.return_value = info("8.15.0")
    with pytest.raises(ESConfigError):
        Database(client).check()
    client.info.side_effect = make_error(
        "BadRequestError", 400, {"error": "media_type_header_exception"}
    )
    with pytest.raises(ESConfigError):
        Database(client).check()


def test_indices_hides_system_ones(client):
    client.cat.indices.return_value = [
        {"index": ".sys", "docs.count": "1"}, {"index": "shop", "docs.count": "3"},
    ]
    assert [(i.name, i.docs) for i in Database(client).indices()] == [("shop", 3)]


def run_cli(client, *argv):
    cli.run(Database(client), cli.build_parser().parse_args(list(argv)))


def test_cli_search_uses_schema(client, capsys):
    client.indices.get_mapping.return_value = MAPPING
    client.search.return_value = search_response(("1", {"title": "سلام"}))
    run_cli(client, "search", "a", "--eq", "title=x", "--match", "body=y")
    query = client.search.call_args.kwargs["body"]["query"]["bool"]
    assert query["filter"] == [{"term": {"title.keyword": {"value": "x"}}}]
    assert "سلام" in capsys.readouterr().out


def test_cli_export_limit_and_no_overwrite(client, tmp_path):
    client.open_point_in_time.return_value = {"id": "p"}
    client.search.return_value = search_response(("1", {}), ("2", {}))
    out = tmp_path / "out.jsonl"
    run_cli(client, "export", "a", "--limit", "1", "--out", str(out))
    assert out.read_text().count("\n") == 1
    client.close_point_in_time.assert_called_once()
    with pytest.raises(FileExistsError):
        run_cli(client, "export", "a", "--out", str(out))


def test_cli_reports_config_errors(monkeypatch, capsys):
    monkeypatch.setenv("ES_MAX_RETRIES", "x")
    assert cli.main(["check"]) == 1
    assert "error:" in capsys.readouterr().err


def test_cli_wraps_nested_fields(client):
    client.indices.get_mapping.return_value = MAPPING
    client.search.return_value = search_response()
    run_cli(client, "search", "a", "--eq", "comments.by=ali")
    clause = client.search.call_args.kwargs["body"]["query"]["bool"]["filter"][0]
    assert clause["nested"]["path"] == "comments"
