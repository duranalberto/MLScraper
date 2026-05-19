# Configuration

Runtime configuration lives in `config/`. Secrets are optional and stay out of
Git.

## `config/jobs.yaml`

Defines the active scraping catalogue under a top-level `jobs` list.

Every job requires:

- `provider`: one of `ml`, `az`, `lv`, or `ph`.
- `search_term`: human-readable label used for scraping and storage naming.

Provider-specific fields:

- Mercado Libre (`ml`): optional `category`, optional `url`.
- Amazon (`az`): optional `seller`.
- Liverpool (`lv`): required `url`.
- Palacio de Hierro (`ph`): required `url`.

Use `config/jobs.yaml.example` as a safe starting template.

## `config/motors.yaml`

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

## `config/scrapper.yaml`

Controls scheduler-level backoff policy:

- `BACKOFF_INITIAL`: first scheduler backoff after a provider loop error.
- `BACKOFF_MAX`: maximum scheduler backoff after repeated provider loop errors.

Provider concurrency is configured with `CONCURRENCY_LIMIT` in
`config/motors.yaml`. The current scrape cycle sleep is set in
`Scrapper.sleep_time`.

## Telegram

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
