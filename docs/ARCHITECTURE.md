# Architecture

MLScraper is a scheduled scraper service wrapped by a FastAPI application with
a hybrid in-memory + MySQL persistence layer and an asynchronous queue-backed
observer notification system.

## Runtime Flow

1. `app.py` creates the FastAPI app (or runs the `preview-url` CLI subcommand).
2. The FastAPI lifespan hook starts `Scrapper.run()` as a background task.
3. `Scrapper` loads configured motors from `config/jobs.yaml`.
4. Each store/provider (`az`, `lv`, `ml`, `ph`) hydrates a shared in-memory
   `ProviderCatalog` Identity Map from MySQL (`utils/db.py`) and attaches
   canonical `Article` references into each `Motor`'s search streams.
5. Each provider runs an independent scheduler loop with bounded concurrency.
6. Each `Motor` fetches pages (`aiohttp` or Playwright `browser`), parses pages
   via its `PageScrapeStrategy`, synchronizes discoveries/updates through
   `ProviderCatalog` (First-Writer-Wins & Compare-And-Swap), reconciles missing
   items in $O(N + M)$ in-memory set operations, flushes cycle state and
   `scrape_runs` telemetry to MySQL, and enqueues notification events onto
   `NotificationDispatcher`.
7. `NotificationDispatcher` drains its `asyncio.Queue` in the background,
   evaluates notification rules, deduplicates/logs events in
   `notification_events`, and fans out alerts to registered
   `NotificationObserver`s (such as `TelegramObserver`).

`GET /health` returns the service status plus per-provider cycle and queue
details. It returns `503` while the scraper is still starting.

## Core Modules

- `app.py`: FastAPI entrypoint, `/health` endpoint, and `preview-url` CLI subcommand.
- `scraper/runtime/orchestrator.py`: scraper orchestrator scheduling per-provider
  scrape loops and managing `NotificationDispatcher`.
- `scraper/runtime/notifications.py`: `NotificationDispatcher` (`asyncio.Queue`
  producer-consumer) and `NotificationObserver` protocol.
- `scraper/runtime/telegram_notifications.py`: `TelegramObserver` and
  `TelegramNotifier`.
- `shared/scraping/motor.py`: shared motor base coordinating fetchers,
  `PageScrapeStrategy`, `ProviderCatalog`, `ArticleLifecycle`, and
  `ArticleRepository`.
- `shared/scraping/page_strategy.py`: `PageScrapeStrategy` protocol,
  `PageScrapeResult`, and `FallbackPageScrapeStrategy`.
- `shared/scraping/fetchers.py`: `aiohttp` and Playwright browser fetch
  strategies with an Open/Closed fetcher registry.
- `shared/articles/article.py`: `Article` model with automatic price watermarks
  (`initial_price`, `lowest_price`, `highest_price`) and history management.
- `shared/articles/catalog.py`: per-store `ProviderCatalog` Identity Map,
  Compare-And-Swap synchronization, and Strict Status Dominance calculation.
- `shared/articles/lifecycle.py`: `ArticleLifecycle` state machine.
- `shared/articles/repository.py`: `ArticleRepository` supporting relational
  catalog persistence and JSON file storage.
- `utils/db.py`: 8-table MySQL / SQLite relational persistence backends
  (`MySQLPersistenceBackend`, `SQLitePersistenceBackend`).

## Provider Boundaries

Each provider owns its URL construction, `PageScrapeStrategy` implementation,
enums/options, selectors, and provider-specific fallbacks inside `provider/<name>/`:

- `az`: Amazon (`provider/amazon/`)
- `ml`: Mercado Libre (`provider/mercado_libre/`)
- `lv`: Liverpool (`provider/liverpool/`)
- `ph`: Palacio de Hierro (`provider/palacio_de_hierro/`)

Shared contracts used by both provider implementations and scraper
orchestration live in `shared/`. `shared/` must not import from `provider/` or
`scraper/`.
