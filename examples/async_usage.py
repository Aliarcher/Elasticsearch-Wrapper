"""Run: pip install -e ".[async]" && python examples/async_usage.py (after basic.py)"""

import asyncio

from eskit import AsyncESManager, AsyncRepository, ESSettings, F, QueryBuilder


async def main() -> None:
    async with AsyncESManager() as es:
        es.configure(ESSettings.from_env())
        products = AsyncRepository(es.client(), index="eskit-demo-products")
        cheap = QueryBuilder().filter(F("price") < 1000)
        print(await products.count(cheap))
        async for hit in products.iter_all(cheap, batch_size=100):
            print(hit.source)


if __name__ == "__main__":
    asyncio.run(main())
