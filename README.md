# MLScraper

MLScraper is a Python and FastAPI product tracker for online stores. It runs
configured scraping jobs on a schedule, stores product snapshots under `data/`,
and can send Telegram notifications for new listings and price drops.

Supported providers:

- Amazon Mexico
- Mercado Libre
- Liverpool
- Palacio de Hierro

## Quick Start

Develop with the VS Code dev container by rebuilding and reopening the project
in the container. The image installs runtime dependencies, developer tools, and
Playwright Chromium during build. It also configures Zsh with Oh My Zsh,
Powerlevel10k, `zsh-autosuggestions`, and `zsh-syntax-highlighting`.

Run locally:

```bash
python3 -m pip install -r requirements.txt
python3 -m playwright install --with-deps chromium
source venv/bin/activate && python3 app.py
```

The service listens on port `80` and exposes:

```text
GET /health
```

Generate one configured job URL on demand (without running scraper loops):

```bash
source venv/bin/activate && python3 app.py preview-url --provider lv --job-id "PlayStation"
```

Run tests:

```bash
source venv/bin/activate && python3 -m unittest discover -v
```

Optional developer checks:

```bash
python3 -m pip install -r requirements-dev.txt
pyright
ruff check .
black --check .
pre-commit run --all-files
```

## Configuration

Runtime configuration lives in `config/`:

- `config/jobs.yaml` defines the scraping jobs to run.
- `config/motors.yaml` defines provider fetch, delay, backoff, and concurrency policy.
- `config/scrapper.yaml` defines scheduler-level backoff values.
- `config/telegram.yaml.example` is the template for optional Telegram credentials.

Copy the Telegram example only if you want notifications:

```bash
cp config/telegram.yaml.example config/telegram.yaml
```

`config/telegram.yaml` is ignored by Git and must never be committed.

By default, persisted product JSON is stored under `./data`. Set `DATA_PATH` if
you need to use a different storage directory.

## Configuration Details

### `config/jobs.yaml`

Defines the active scraping catalogue under a top-level `jobs` list.

Every job requires:
- `provider`: one of `ml`, `az`, `lv`, or `ph`.
- `job_id`: stable provider-local job identifier used for runtime labelling and
  storage naming. Keep the value stable to keep the same data source.

All provider factories must support these shared job parameters:
- `job_id`: required stable identity.
- `url`: optional explicit URL bypass.
- `query`: optional human-readable search text adapted by each provider.

When a non-blank `url` is present, it is the only authoritative route input.
Provider-specific generated option fields are ignored for URL generation even if
those option values are invalid or unsupported.

`job_id` must be unique within each provider. The same value can be reused by
different providers, such as one `Apple` job for Liverpool and one for Palacio,
but a provider cannot define two `Apple` jobs.

Provider-specific fields:

- **Mercado Libre (`ml`)**: optional `url`, optional global or seller-scoped
  `query`, optional known `seller`, optional documented `category`, and optional
  `state` (`nuevo` or `usado`). Generated global searches require `query`.
  Known seller jobs can list all products, add a query,
  or use documented category routes. Store `state` filters require a category
  route in generated jobs; use explicit `url` for unmodeled Mercado Libre
  routes.
- **Amazon (`az`)**: optional `url`, optional search `query`, optional known
  `seller`, and optional documented singular `brand`. Generated search text
  comes from `query`; refinement-only jobs can omit it when `seller` or `brand`
  already form the URL. Explicit `url` is used unchanged for unmodeled
  refinements or copied browser URLs.
- **Liverpool (`lv`)**: optional `url`, optional `query`, optional Liverpool
  `page`, and optional seeded `talla` filters for `zapatos_hombre`. Generated URLs
  resolve Liverpool's seller filter at job creation.
  Page + query jobs use the root `N-` token route so Liverpool preserves both
  seller and page refinements.
  `talla` currently supports seeded `zapatos_hombre` combinations only and rejects
  unsupported values/combinations.
  Legacy `category` is accepted as an alias for `page`. Explicit `url` is the
  only bypass and is used unchanged, including custom sellers or unmodeled
  filter combinations.
- **Palacio de Hierro (`ph`)**: optional `url`, optional global search `query`,
  optional Palacio `page`, and optional page-scoped `brands`. Generated global
  searches require `query`. Generated brand filters require a page route.
  Explicit `url` is used unchanged for unmodeled route or filter combinations.

Use `config/jobs.yaml.example` as a safe starting template.

### `config/motors.yaml`

Controls motor-level scraping policy. `defaults` apply to all providers unless
a provider class overrides them.

Important keys:

- `PAGE_DELAY_RANGE`: minimum and maximum delay between paginated pages.
- `FRESH_SESSION_PER_PAGE`: whether each page gets a new HTTP session.
- `MAX_RATE_LIMIT_RETRIES`: retry limit for rate-limit responses.
- `RATE_LIMIT_SLEEP_CAP`: maximum retry sleep from rate-limit handling.
- `BLOCKED_BACKOFF_SECONDS`: cooldown after a block or gate.
- `CONCURRENCY_LIMIT`: provider-level concurrent job limit.
- `FETCH_STRATEGY`: `aiohttp` or `browser`.
- `FETCH_TIMEOUT_SECONDS`: fetch timeout in seconds.
- `BROWSER_WAIT_SELECTOR`: selector that indicates a browser page is ready.
- `BROWSER_BLOCK_SELECTORS`: selectors or `url*=` fragments that indicate a
  blocked browser page.

Provider-specific sections use class names such as `Amazon`, `MercadoLibre`,
`Liverpool`, and `PalacioDeHierro`.

### `config/scrapper.yaml`

Controls scheduler-level backoff policy:

- `BACKOFF_INITIAL`: first scheduler backoff after a provider loop error.
- `BACKOFF_MAX`: maximum scheduler backoff after repeated provider loop errors.

Provider concurrency is configured with `CONCURRENCY_LIMIT` in
`config/motors.yaml`. The current scrape cycle sleep is set in
`Scrapper.sleep_time`.

### Telegram

Telegram notifications are optional. To enable them:

```bash
cp config/telegram.yaml.example config/telegram.yaml
```

Then fill in:
- `api_token`: bot token from BotFather.
- `chat_id`: destination chat ID.

`config/telegram.yaml` is ignored by Git and must not be committed.

When the file is missing or blank, the app logs a warning and notifications are
disabled without crashing the service.

## Data Path

`utils/file_manager.py` reads `DATA_PATH` from the environment. If it is not set,
the app uses `./data`. Set `DATA_PATH` to point runtime JSON storage at another
directory. Storage paths must stay relative to `DATA_PATH`.

The historical tracked archive `data/data.zip` is left untouched by normal
config/helper maintenance. Remove it from tracking only as part of an explicit
data cleanup.

## Architecture

MLScraper is a scheduled scraper service wrapped by a small FastAPI app.

### Runtime Flow

1. `app.py` creates the FastAPI app.
2. The FastAPI lifespan hook starts `Scrapper.run()` as a background task.
3. `Scrapper` loads configured motors from `config/jobs.yaml`.
4. Each provider gets an independent scheduler loop.
5. Each `Motor` fetches pages, parses provider results, reconciles product
   state, persists JSON, and emits notification events.
6. Telegram helpers send messages when credentials are configured.

`GET /health` returns the service status plus per-provider cycle and queue
details. It returns `503` while the scraper is still starting.

### Core Modules

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

### Provider Boundaries

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

### Fetching

Motors use `FETCH_STRATEGY` from `config/motors.yaml`.

- `aiohttp` is the default lightweight HTTP fetcher.
- `browser` uses Playwright Chromium for pages that need browser rendering or
  selector-based readiness checks.

Browser mode can mark a motor as blocked when configured selectors or URL
fragments indicate a gate, timeout, or anti-bot page.

### Persistence

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

## Project Map

- `app.py` creates the FastAPI app and starts the background scraper task.
- `scraper/runtime/orchestrator.py` starts provider loops while scraper helpers
  handle concurrency, health, and notification routing.
- `shared/` contains shared article, stream, fetcher, motor, lifecycle, and
  persistence contracts used by both providers and scraper orchestration.
- `scraper/` contains job assembly and runtime orchestration helpers.
- `provider/` contains provider-specific motors, parsers, URLs, and options.
- `utils/` contains persistence, Telegram, header profiles, and supporting helpers.
- `tests/` contains the current regression suite.

More detail:
- [Architecture](docs/ARCHITECTURE.md)
- [Data Model](docs/DATA_MODEL.md)
- [Amazon](docs/AMAZON.md)
- [Mercado Libre](docs/MERCADO_LIBRE.md)
- [Liverpool](docs/LIVERPOOL.md)
- [Palacio de Hierro](docs/PALACIO_DE_HIERRO.md)
- [Testing](docs/TESTING.md)
- [Adding a Provider](docs/ADDING_PROVIDER.md)
- [Operations](docs/OPERATIONS.md)
- [Contributing](CONTRIBUTING.md)
- [Security](SECURITY.md)

## Documentation Style

Project docstrings use the Google-style convention documented in
[Contributing](CONTRIBUTING.md#documentation-and-docstrings). Public modules,
classes, provider contracts, parsers, fetchers, factories, persistence helpers,
notifications, and orchestration code should document parameters, return values,
intentional exceptions, side effects, and scraper-specific assumptions when
those details are not obvious from the signature.

## Working With LLM Agents

This repository includes root guidance files for coding agents:

- `AGENTS.md` for Codex
- `CLAUDE.md` for Claude

Both files tell agents how to work safely in this project: avoid changing
runtime data, keep provider-specific logic isolated, keep shared contracts in
`shared/`, and run the relevant checks after behavior changes.
