# Changelog

## 0.2.0
- Added `Database` / `AsyncDatabase` (read-only by default), `Schema`, and the `eskit` CLI.
- Breaking: dict documents use `_id` (previously `id`); stored `id` fields are preserved.
- Dataclass models ignore undeclared fields.

## 0.1.0
- First version.
