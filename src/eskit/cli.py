"""Read-only command line tool. Connection settings come from ES_* variables."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from itertools import islice
from typing import Any

from .config import ESSettings
from .connection import ESManager
from .database import Database
from .exceptions import ESKitError
from .query import QueryBuilder, nested
from .query.expressions import Expr
from .repository import Repository


def _positive(raw: str) -> int:
    value = int(raw)
    if value < 1:
        raise argparse.ArgumentTypeError("must be >= 1")
    return value


def _pair(raw: str) -> tuple[str, str]:
    name, sep, value = raw.partition("=")
    if not sep or not name:
        raise argparse.ArgumentTypeError("expected field=value")
    return name, value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="eskit", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check", help="test the connection and versions")
    listing = commands.add_parser("indices", help="list indices")
    listing.add_argument("pattern", nargs="?", default="*")
    schema = commands.add_parser("schema", help="show fields and types")
    schema.add_argument("index")
    for name, help_text in (("search", "print matching documents"),
                            ("export", "write all matches as JSON lines")):
        sub = commands.add_parser(name, help=help_text)
        sub.add_argument("index")
        sub.add_argument("--eq", type=_pair, action="append", default=[], metavar="FIELD=VALUE")
        sub.add_argument("--match", type=_pair, action="append", default=[], metavar="FIELD=TEXT")
        if name == "search":
            sub.add_argument("--size", type=_positive, default=10)
        else:
            sub.add_argument("--limit", type=_positive)
            sub.add_argument("--out", help="output file (default: stdout); must not exist")
    return parser


def _query(db: Database, args: argparse.Namespace) -> QueryBuilder:
    query = QueryBuilder()
    if args.eq or args.match:
        schema = db.schema(args.index)
        # Each condition on a nested field is matched independently.
        def wrap(name: str, expr: Expr) -> Expr:
            path = schema.field(name).nested_path
            return nested(path, expr) if path else expr

        for name, value in args.eq:
            query = query.filter(wrap(name, schema.exact(name) == value))
        for name, text in args.match:
            query = query.must(wrap(name, schema.text(name).match(text)))
    return query


def _line(document: Any) -> str:
    return json.dumps(document, ensure_ascii=False)


def run(db: Database, args: argparse.Namespace) -> None:
    if args.command == "check":
        server = db.check()
        print(f"OK: cluster={server.cluster_name} version={server.version}")
    elif args.command == "indices":
        for item in db.indices(args.pattern):
            print(f"{item.name}\t{item.health}\t{item.docs}\t{item.size}")
    elif args.command == "schema":
        for name, info in sorted(db.schema(args.index).fields.items()):
            nested = f"\t(nested: {info.nested_path})" if info.nested_path else ""
            print(f"{name}\t{','.join(info.types)}{nested}")
    elif args.command == "search":
        searcher: Repository[dict[str, Any]] = db.repository(args.index)
        result = searcher.search(_query(db, args).size(args.size))
        for document in result:
            print(_line(document))
        print(f"total={result.total} exact={result.total_is_exact}", file=sys.stderr)
    else:
        repo: Repository[dict[str, Any]] = db.repository(args.index)
        query = _query(db, args)
        batch = min(args.limit or 1000, 1000)
        out = open(args.out, "x", encoding="utf-8") if args.out else sys.stdout
        hits = repo.iter_all(query, batch_size=batch)
        try:
            count = 0
            for hit in islice(hits, args.limit):
                print(_line(hit.source), file=out)
                count += 1
            print(f"exported={count}", file=sys.stderr)
        finally:
            hits.close()  # type: ignore[attr-defined]
            if args.out:
                out.close()


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        with ESManager() as manager:
            manager.configure(ESSettings.from_env())
            run(Database(manager.client(), read_only=True), args)
    except (ESKitError, OSError, ImportError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
