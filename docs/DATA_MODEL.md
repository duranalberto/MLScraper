# Data Model

MLScraper persists one JSON list per configured motor. Files live below
`DATA_PATH`, which defaults to `./data`.

## Article Record

Each persisted record is created by `scraper.article.Article.dump()`.

Required fields:

- `identifier`: stable provider identifier.
- `title`: product title.
- `price`: numeric product price.
- `datetime`: first-seen timestamp.
- `status`: lifecycle status.

Optional fields:

- `url`: product URL.
- `last_updated`: timestamp for the latest title or price change.
- `history`: prior title or price values.
- `status_history`: recorded lifecycle transitions.
- `hold_misses`: count used by missing-item reconciliation.

Example:

```json
{
  "identifier": "MLM123",
  "title": "Nintendo 3DS",
  "price": 3200.0,
  "url": "https://example.test/item",
  "datetime": "2026-05-16 12:00:00",
  "status": "active"
}
```

## Status Values

Statuses are defined in `scraper/status.py`:

- `none`
- `active`
- `on_hold`
- `finished`
- `ignoring`

Current reconciliation flow moves missing active records to `on_hold` first.
After repeated misses, records move to `finished`.

## History

`history` stores previous title or price values when an active item changes.
`status_history` stores lifecycle transitions that matter to the hold/finish
flow. Histories are capped by `MAX_HISTORY` in `scraper/article.py`.

## Reads and Writes

`utils/file_manager.py` handles persistence:

- paths are resolved below `DATA_PATH`.
- relative paths are required for normal writes.
- parent-directory traversal is rejected.
- writes go through a temporary file.
- an existing file is copied to a `.bak` backup before replacement.
- invalid primary JSON can recover from the backup when possible.

Do not edit runtime data files as part of normal code changes.
