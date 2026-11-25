"""Using elasticsearch.dsl Document models together with eskit."""

from elasticsearch.dsl import Keyword, Text

from eskit import ESManager, ESSettings, F, QueryBuilder
from eskit.documents import TimestampedDocument


class Article(TimestampedDocument):
    title = Text()
    tag = Keyword()

    class Index:
        name = "eskit-demo-articles"


def main() -> None:
    with ESManager() as es:
        es.configure(ESSettings.from_env())
        es.client()  # also registers the "default" DSL connection
        Article.init()
        Article(title="Hello Elasticsearch", tag="python").save(refresh=True)

        search = (
            QueryBuilder()
            .must(F("title").match("hello"))
            .filter(F("tag") == "python")
            .to_search(index=Article.Index.name)
        )
        for hit in search.execute():
            print(hit.title)


if __name__ == "__main__":
    main()
