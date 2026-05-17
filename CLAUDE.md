# Claude Guidance for MLScraper

This file is the operating guide for Claude and other LLM coding assistants
working in this repository.

## Project Rules

- Preserve the current runtime layout. `app.py`, `scrapper.py`, `scraper/`,
  `provider/`, `utils/`, `config/`, and `tests/` are the core boundaries.
- Do not mutate tracked or local scraper data under `data/` unless the user
  explicitly asks for a data migration or cleanup.
- Never commit `config/telegram.yaml` or real Telegram credentials.
- Use fast repository search such as `rg` or `rg --files`.
- Prefer the existing provider registry and factory pattern in
  `provider/registry.py` and `provider/factories.py`.
- Keep provider parsing isolated in provider modules. Shared behavior belongs in
  `scraper/` only when more than one provider needs it.
- Keep config names aligned with the current YAML files:
  `config/jobs.yaml`, `config/motors.yaml`, and `config/scrapper.yaml`.
- Run `python -m unittest discover -v` after behavior changes.
- For docs-only changes, verify links and command names against the repo.

## Common Commands

```bash
python -m unittest discover -v
docker compose up --build
ruff check .
black --check .
```

Install optional developer tools first:

```bash
python -m pip install -r requirements-dev.txt
```

## Implementation Notes

- `Scrapper` runs one loop per provider and limits concurrency per provider.
- `Motor` owns shared scrape, fetch, persistence, and reconciliation flow.
- Provider factories convert job entries into concrete motors and storage paths.
- Fetching uses either `aiohttp` or Playwright browser mode based on
  `FETCH_STRATEGY`.
- Persisted product records are JSON lists below `DATA_PATH`.

When adding or changing behavior, update the docs if setup, config, provider
interfaces, or operational expectations change.
