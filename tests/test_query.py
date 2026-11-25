import pytest

from eskit import Agg, F, QueryBuilder, nested


def test_empty_is_match_all():
    assert QueryBuilder().to_dict() == {"query": {"match_all": {}}}


def test_operators_flatten():
    expr = (F("a") == 1) & (F("b") == 2) & (F("c") == 3)
    assert len(expr.to_dict()["bool"]["must"]) == 3
    either = (F("a") == 1) | (F("b") == 2)
    assert either.to_dict()["bool"]["minimum_should_match"] == 1
    assert (~~expr) is expr


def test_none_means_missing_field():
    assert (F("a") == None).to_dict() == {  # noqa: E711
        "bool": {"must_not": [{"exists": {"field": "a"}}]}
    }


def test_python_boolean_operators_are_rejected():
    with pytest.raises(TypeError):
        (F("a") == 1) and (F("b") == 2)
    with pytest.raises(TypeError):
        1 < F("a") < 5


def test_builder_is_immutable():
    base = QueryBuilder().filter(F("a") == 1)
    base.filter(F("b") == 2).sort("-a")
    assert base.to_dict() == {"query": {"bool": {"filter": [{"term": {"a": {"value": 1}}}]}}}


def test_when_skips_empty_but_keeps_zero():
    def apply(q, v):
        return q.filter(F("a") == v)

    base = QueryBuilder()
    for empty in (None, "", []):
        assert base.when(empty, apply) is base
    assert base.when(0, apply) is not base


def test_full_body():
    body = (
        QueryBuilder()
        .must(F("title").match("x"))
        .should(F("tag") == "a", minimum_should_match=1)
        .exclude(F("hidden") == True)  # noqa: E712
        .sort("-price", "name", "_score")
        .paginate(3, 20)
        .agg("b", Agg.terms("brand").sub("p", Agg.avg("price")))
        .to_dict()
    )
    assert body["from"] == 40 and body["size"] == 20
    assert body["sort"] == [{"price": {"order": "desc"}}, {"name": {"order": "asc"}}, "_score"]
    assert body["aggs"]["b"]["aggs"]["p"] == {"avg": {"field": "price"}}
    assert body["query"]["bool"]["minimum_should_match"] == 1


def test_limits_and_validation():
    with pytest.raises(ValueError):
        QueryBuilder().paginate(1001, 10)
    with pytest.raises(ValueError):
        F("a").between(None, None)
    with pytest.raises(TypeError):
        F("a").isin("abc")


def test_wildcard_input_is_escaped():
    value = F("n").contains("a*b?").to_dict()["wildcard"]["n"]["value"]
    assert value == "*a\\*b\\?*"


def test_accepts_dicts_and_dsl_like_objects():
    class DslQuery:
        def to_dict(self):
            return {"match_all": {}}

    assert nested("c", DslQuery()).to_dict()["nested"]["query"] == {"match_all": {}}
    assert QueryBuilder().filter({"ids": {"values": ["1"]}}).query_dict()["bool"]["filter"]


def test_knn_only_has_no_match_all():
    assert "query" not in QueryBuilder().option("knn", {"field": "v"}).to_dict()
