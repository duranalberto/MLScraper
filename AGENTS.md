# Codex Guidance for MLScraper

This file is the operating guide for Codex and other agentic coding tools
working in this repository.

## Project Rules

- Preserve the current runtime layout. `app.py`, `shared/`, `scraper/`,
  `provider/`, `utils/`, `config/`, and `tests/` are the core boundaries.
- Keep the repository root free of Python modules except `app.py`.
- Do not mutate tracked or local scraper data under `data/` unless the user
  explicitly asks for a data migration or cleanup.
- Never commit `config/telegram.yaml` or real Telegram credentials.
- Use `rg` or `rg --files` for repository search.
- Prefer the existing provider registry and factory pattern in `scraper/jobs/`.
- Keep `provider/` limited to provider implementation subpackages. The package
  root should contain only `__init__.py`.
- Keep provider parsing, URL building, options/enums, selectors, and
  provider-local helpers inside the provider subpackage.
- Avoid new generic provider `utils.py` modules; prefer names such as
  `parser.py`, `urls.py`, `options.py`, or `selectors.py`.
- Put stable contracts used by both providers and scraper orchestration in
  `shared/`. `shared/` must not import from `provider/` or `scraper/`.
- Keep `scraper/` for scraper-owned job assembly and runtime orchestration.
- Keep config names aligned with the current YAML files:
  `config/jobs.yaml`, `config/motors.yaml`, and `config/scrapper.yaml`.
- Follow the Google-style docstring standard in
  `CONTRIBUTING.md#documentation-and-docstrings`. Public modules, classes,
  methods, provider contracts, parsers, fetchers, factories, persistence,
  notifications, and orchestration code should document parameters, return
  values, intentional exceptions, side effects, and scraper-specific assumptions
  when those details are not obvious from the signature.
- Do not add docstring lint enforcement until the existing public API has been
  documented.
- Run `python -m unittest discover -v` after behavior changes.
- For docs-only changes, still verify links and command names against the repo.

## Common Commands

```bash
python -m unittest discover -v
pyright
ruff check .
black --check .
```

Install optional developer tools first:

```bash
python -m pip install -r requirements-dev.txt
```

## Implementation Notes

- `Scrapper` in `scraper/runtime/orchestrator.py` runs one loop per provider
  and limits concurrency per provider.
- `Motor` in `shared/scraping/` owns shared scrape, fetch, persistence, and
  reconciliation flow.
- Provider factories in `scraper/jobs/` convert job entries into concrete motors
  and storage paths.
- Fetching uses either `aiohttp` or Playwright browser mode based on
  `FETCH_STRATEGY`.
- Persisted product records are JSON lists below `DATA_PATH`.

When adding or changing behavior, update the docs if setup, config, provider
interfaces, or operational expectations change.
