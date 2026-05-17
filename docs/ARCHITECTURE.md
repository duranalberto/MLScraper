# Architecture

MLScraper is a scheduled scraper service wrapped by a small FastAPI app.

## Runtime Flow

1. `app.py` creates the FastAPI app.
2. The FastAPI lifespan hook starts `Scrapper.run()` as a background task.
3. `Scrapper` loads configured motors from `config/jobs.yaml`.
4. Each provider gets an independent scheduler loop.
5. Each `Motor` fetches pages, parses provider results, reconciles product
   state, persists JSON, and emits notification events.
6. Telegram helpers send messages when credentials are configured.

`GET /health` returns the service status plus per-provider cycle and queue
details. It returns `503` while the scraper is still starting.

## Core Modules

- `app.py`: FastAPI entrypoint and health endpoint.
- `scraper/runtime/orchestrator.py`: public scraper orchestrator; delegates
  provider concurrency, health aggregation, and notification routing to focused
  helpers.
- `scraper/runtime/config.py`: scheduler-level config loader for
  `config/scrapper.yaml`.
- `shared/scraping/motor.py`: public shared motor base; delegates config,
  persistence, lifecycle transitions, and missing-item reconciliation to focused
  helpers.
- `shared/scraping/fetchers.py`: `aiohttp` and Playwright browser fetch
  strategies.
- `shared/articles/article.py`: persisted product and history data classes.
- `scraper/jobs/registry.py`: provider factory registry.
- `scraper/jobs/factories.py`: job-to-motor construction and storage path naming.
- `scraper/jobs/loader.py`: YAML job loading, validation, and enum coercion.
- `scraper/runtime/`: provider concurrency, health, and notification helpers.
- `utils/file_manager.py`: safe JSON reads and atomic writes below `DATA_PATH`.
- `utils/headers.py`: request header rendering over shared browser profiles.
- `utils/telegram.py`: optional Telegram notification integration.

## Provider Boundaries

Each provider owns its URL construction, parsing, enums/options, selectors, and
provider-specific fallbacks. Larger providers can split parser helpers inside
their provider package.

Shared contracts used by both provider implementations and scraper
orchestration live in `shared/`. `shared/` must not import from `provider/` or
`scraper/`. Scraper-owned job assembly and runtime orchestration live in
`scraper/`.

Current provider keys:

- `az`: Amazon
- `ml`: Mercado Libre
- `lv`: Liverpool
- `ph`: Palacio de Hierro

## Fetching

Motors use `FETCH_STRATEGY` from `config/motors.yaml`.

- `aiohttp` is the default lightweight HTTP fetcher.
- `browser` uses Playwright Chromium for pages that need browser rendering or
  selector-based readiness checks.

Browser mode can mark a motor as blocked when configured selectors or URL
fragments indicate a gate, timeout, or anti-bot page.

## Persistence

Product records are stored as JSON lists below `DATA_PATH`, defaulting to
`./data`. Writes use a temporary file and keep a `.bak` copy of the previous
file when possible.

Factory-generated paths group data by provider, for example:

```text
amazon/macbook__amazon-mx.json
mercado_libre/pokemon-ds__consolas.json
liverpool/laptops.json
palacio_de_hierro/macbook.json
```
