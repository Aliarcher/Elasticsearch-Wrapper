import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from conftest import make_error, search_response

from eskit import (
    AsyncESManager, AsyncRepository, ESConfigError, ESKitError, ESManager, ESSettings,
    IndexManager,
)


def test_settings_from_env_and_secret_hidden():
    env = {"ES_HOSTS": "http://a:9200, http://b:9200", "ES_API_KEY": "s3cret"}
    settings = ESSettings.from_env(environ=env)
    kwargs = settings.client_kwargs()
    assert kwargs["hosts"] == ["http://a:9200", "http://b:9200"]
    assert kwargs["api_key"] == "s3cret" and "verify_certs" not in kwargs
    assert "s3cret" not in repr(settings)


@pytest.mark.parametrize(
    "bad",
    [
        {},
        {"hosts": ("h",), "cloud_id": "c"},
        {"hosts": ("h",), "username": "u"},
        {"hosts": ("h",), "api_key": "k", "bearer_token": "t"},
    ],
)
def test_settings_validation(bad):
    with pytest.raises(ESConfigError):
        ESSettings(**bad)


def test_bad_env_values():
    for env in ({"ES_VERIFY_CERTS": "maybe"}, {"ES_MAX_RETRIES": "x"}):
        with pytest.raises(ESConfigError):
            ESSettings.from_env(environ=env)


def test_manager_is_lazy_cached_and_closes():
    factory = MagicMock()
    with ESManager(factory=factory) as manager:
        manager.configure(ESSettings(hosts=("http://x:9200",)))
        factory.assert_not_called()
        assert manager.client() is manager.client()
        factory.assert_called_once()
    factory.return_value.close.assert_called_once()
    with pytest.raises(ESConfigError):
        manager.client("other")


def test_async_manager_and_repository():
    fake = MagicMock()
    fake.close = AsyncMock()
    fake.open_point_in_time = AsyncMock(return_value={"id": "p"})
    fake.close_point_in_time = AsyncMock()
    fake.search = AsyncMock(side_effect=[search_response(("1", {"n": 1})), search_response()])

    async def run():
        async with AsyncESManager(factory=lambda **_: fake) as manager:
            manager.configure(ESSettings(hosts=("http://x:9200",)))
            repo = AsyncRepository(manager.client(), index="i")
            return [h.source async for h in repo.iter_all()]

    assert asyncio.run(run()) == [{"n": 1, "_id": "1"}]
    fake.close.assert_awaited_once()
    fake.close_point_in_time.assert_awaited_once_with(id="p")


@pytest.mark.parametrize("name", ["", "*", "_all", "a*", "a,b"])
def test_refuses_dangerous_delete(name):
    client = MagicMock()
    with pytest.raises(ESConfigError):
        IndexManager(client).delete(name)
    client.indices.delete.assert_not_called()


def migrating_client():
    client = MagicMock()
    client.indices.exists_alias.return_value = True
    client.indices.get_alias.return_value = {"p-old": {}}
    return client


def test_migrate_swaps_alias():
    client = migrating_client()
    client.options.return_value.reindex.return_value = {"failures": []}
    new = IndexManager(client).migrate("p")
    actions = client.indices.update_aliases.call_args.kwargs["actions"]
    assert actions[0] == {"remove": {"index": "p-old", "alias": "p"}}
    assert actions[1]["add"]["index"] == new


def test_migrate_rolls_back_on_failures():
    client = migrating_client()
    client.options.return_value.reindex.return_value = {"failures": [{"x": 1}]}
    with pytest.raises(ESKitError):
        IndexManager(client).migrate("p")
    client.indices.update_aliases.assert_not_called()
    client.indices.delete.assert_called_once()


def test_migrate_keeps_new_index_on_timeout():
    client = migrating_client()
    client.options.return_value.reindex.side_effect = make_error("ConnectionTimeout")
    with pytest.raises(ESKitError):
        IndexManager(client).migrate("p")
    client.indices.delete.assert_not_called()
