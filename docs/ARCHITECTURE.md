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
- `scrapper.py`: scheduler, provider concurrency control, health aggregation,
  and notification routing.
- `scraper/motor.py`: shared motor lifecycle, fetching, pagination,
  persistence, and missing-item reconciliation.
- `scraper/fetchers.py`: `aiohttp` and Playwright browser fetch strategies.
- `scraper/article.py`: persisted product and history data classes.
- `provider/registry.py`: provider factory registry.
- `provider/factories.py`: job-to-motor construction and storage path naming.
- `provider/loader.py`: YAML job loading, validation, and enum coercion.
- `utils/file_manager.py`: safe JSON reads and atomic writes below `DATA_PATH`.
- `utils/telegram.py`: optional Telegram notification integration.

## Provider Boundaries

Each provider owns its URL construction, parsing, enums, and provider-specific
fallbacks. Shared scheduling and lifecycle behavior stays in `scraper/`.

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
