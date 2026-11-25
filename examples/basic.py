"""Run: docker compose up -d && pip install -e . && python examples/basic.py"""

from dataclasses import dataclass

from eskit import (
    Agg, ESManager, ESSettings, F, IndexManager, QueryBuilder, Repository, multi_match,
)


@dataclass
class Product:
    id: str
    title: str
    brand: str
    price: float
    in_stock: bool = True


class ProductRepository(Repository[Product]):
    index = "eskit-demo-products"
    model = Product


MAPPINGS = {
    "properties": {
        "title": {"type": "text"},
        "brand": {"type": "keyword"},
        "price": {"type": "double"},
        "in_stock": {"type": "boolean"},
    }
}


def main() -> None:
    with ESManager() as es:
        es.configure(ESSettings.from_env())
        client = es.client()
        IndexManager(client).ensure(ProductRepository.index, mappings=MAPPINGS)
        products = ProductRepository(client)

        products.bulk_save(
            [
                Product("1", "Gaming laptop", "asus", 1500),
                Product("2", "Office laptop", "lenovo", 800),
                Product("3", "Wireless mouse", "logitech", 40, in_stock=False),
            ],
            refresh="wait_for",
        ).raise_for_errors()

        brand = None  # an optional filter coming from a user request
        query = (
            QueryBuilder()
            .must(multi_match("laptop", ["title^2", "brand"]))
            .filter(F("in_stock") == True, F("price").between(500, 2000))  # noqa: E712
            .when(brand, lambda q, value: q.filter(F("brand") == value))
            .agg("brands", Agg.terms("brand").sub("avg_price", Agg.avg("price")))
            .highlight("title")
            .sort("-price")
            .paginate(page=1, per_page=10)
        )
        result = products.search(query)
        print("total:", result.total)
        for hit in result.hits:
            print(hit.source, hit.highlight)
        print(result.aggregations["brands"]["buckets"])


if __name__ == "__main__":
    main()
