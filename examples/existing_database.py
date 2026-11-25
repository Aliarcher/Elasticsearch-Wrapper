"""Explore and read an existing cluster. Set ES_* variables first (see .env.example).

Usage: python examples/existing_database.py INDEX_NAME
"""

import sys

from eskit import Database, ESManager, ESSettings, QueryBuilder


def main(index: str) -> None:
    with ESManager() as es:
        es.configure(ESSettings.from_env())
        db = Database(es.client())  # read-only
        print(db.check())

        schema = db.schema(index)
        for name, field in sorted(schema.fields.items()):
            print(f"{name}: {', '.join(field.types)}")

        repo = db.repository(index)
        result = repo.search(QueryBuilder().size(5).track_total_hits())
        print("total:", result.total)
        for document in result:
            print(document)


if __name__ == "__main__":
    main(sys.argv[1])
