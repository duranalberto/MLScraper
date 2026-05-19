# Testing

MLScraper uses the standard library `unittest` runner. Tests are offline by
default and should not mutate tracked scraper output under `data/`.

Run the suite:

```bash
python -m unittest discover -v
```

Optional checks:

```bash
pyright
ruff check .
black --check .
```

## Test Library Layout

- `tests/test_articles.py` covers `Article`, history, status history, streams,
  and lifecycle transitions.
- `tests/test_config.py` covers runtime and motor configuration parsing,
  coercion, defaults, and provider override precedence.
- `tests/test_fetchers.py` covers HTTP/browser fetch retry, rate-limit, timeout,
  blocked-page, and selector behavior with fakes.
- `tests/test_jobs.py` covers job YAML loading, enum coercion, registry behavior,
  slugging, and provider storage path generation.
- `tests/test_motor_flow.py` covers shared `Motor` scrape flow, incomplete-page
  safeguards, missing-item reconciliation, blocked cooldowns, and broadcast
  payloads.
- `tests/test_notifications.py` covers notification routing, price parsing, and
  price-drop threshold behavior.
- `tests/test_persistence.py` covers JSON persistence, path safety, backup
  recovery, repository loading, and repository saving.
- `tests/test_provider_parsers.py` covers provider parser and URL edge cases.
- `tests/test_threading_and_providers.py` is the existing regression suite for
  package boundaries, provider scheduling, core parser fixtures, and historical
  behavior that has not yet been split into narrower modules.

`tests/helpers.py` contains test-only utilities such as temporary `DATA_PATH`
patching. Keep helpers small and only add them when two or more modules need the
same fake or fixture.

## Practices

- Prefer pure parser/config/lifecycle tests before orchestration tests.
- Use `TemporaryDirectory` or `tests.helpers.PatchedDataPath` for persistence
  tests.
- Patch sleeps in retry and scheduler tests so the suite stays fast.
- Do not start Playwright or make live network requests from unit tests.
- Keep provider HTML fixtures small and focused on the contract under test.
- Add or update parser tests whenever provider selectors, URL rules, or item
  fields change.
