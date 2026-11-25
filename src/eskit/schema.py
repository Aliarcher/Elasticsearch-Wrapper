"""Understand the mapping of an existing index."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .exceptions import ESQueryError
from .query import F

TEXT_TYPES = frozenset({"text", "match_only_text", "search_as_you_type"})
EXACT_TYPES = frozenset({
    "keyword", "constant_keyword", "wildcard", "boolean", "date", "date_nanos", "ip", "version",
    "long", "integer", "short", "byte", "double", "float", "half_float", "scaled_float",
    "unsigned_long",
})


@dataclass(frozen=True)
class FieldInfo:
    name: str
    types: tuple[str, ...]  # more than one means indices disagree
    nested_path: str | None = None
    multi_field_of: str | None = None


class Schema:
    """Fields of one index, alias or pattern, built from the get-mapping response."""

    def __init__(self, fields: dict[str, FieldInfo]) -> None:
        self.fields = fields

    @classmethod
    def from_mapping(cls, response: Mapping[str, Any]) -> Schema:
        found: dict[str, FieldInfo] = {}
        aliases: list[tuple[str, str]] = []

        def add(name: str, kind: str, nested: str | None, parent: str | None = None) -> None:
            old = found.get(name)
            types = set(old.types if old else ()) | {kind}
            found[name] = FieldInfo(name, tuple(sorted(types)), nested, parent)

        def walk(properties: Mapping[str, Any], prefix: str, nested: str | None) -> None:
            for key, spec in properties.items():
                name = prefix + key
                kind = spec.get("type", "object")
                if kind == "alias":
                    aliases.append((name, spec["path"]))
                    continue
                add(name, kind, nested)
                for sub, sub_spec in spec.get("fields", {}).items():
                    add(f"{name}.{sub}", sub_spec["type"], nested, parent=name)
                if "properties" in spec:
                    inner = name if kind == "nested" else nested
                    walk(spec["properties"], name + ".", inner)

        for index in response.values():
            mappings = index.get("mappings", {})
            walk(mappings.get("properties", {}), "", None)
            for name, spec in mappings.get("runtime", {}).items():
                add(name, spec["type"], None)
        for name, target in aliases:
            if target in found:
                info = found[target]
                found[name] = FieldInfo(name, info.types, info.nested_path)
        return cls(found)

    def field(self, name: str) -> FieldInfo:
        try:
            return self.fields[name]
        except KeyError:
            raise ESQueryError(f"Unknown field {name!r}.") from None

    def exact(self, name: str) -> F:
        """The field to use for ==, isin, ranges, sorting and terms aggregations.

        For a text field this picks its keyword sub-field (e.g. "title.keyword").
        Note: values longer than the sub-field's `ignore_above` are not indexed there.
        """
        info = self.field(name)
        if set(info.types) <= EXACT_TYPES:
            return F(name)
        candidates = sorted(
            (f for f in self.fields.values()
             if f.multi_field_of == name and set(f.types) <= EXACT_TYPES),
            key=lambda f: (not f.name.endswith(".keyword"), f.name),
        )
        if candidates:
            return F(candidates[0].name)
        raise ESQueryError(f"Field {name!r} ({', '.join(info.types)}) has no exact-value form.")

    def text(self, name: str) -> F:
        """The field to use for full-text search."""
        info = self.field(name)
        if set(info.types) <= TEXT_TYPES:
            return F(name)
        for f in self.fields.values():
            if f.multi_field_of == name and set(f.types) <= TEXT_TYPES:
                return F(f.name)
        raise ESQueryError(f"Field {name!r} ({', '.join(info.types)}) is not full-text searchable.")

    def text_fields(self) -> list[str]:
        return sorted(n for n, f in self.fields.items() if set(f.types) <= TEXT_TYPES)

    def conflicts(self) -> list[FieldInfo]:
        return [f for f in self.fields.values() if len(f.types) > 1]
