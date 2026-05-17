# Operations

## Docker Compose

Build and run:

```bash
docker compose up --build
```

The app listens on host port `80` and mounts local `./data` to
`/MLScraper/data` inside the container.

Stop the service:

```bash
docker compose down
```

## Local Run

Install dependencies:

```bash
python -m pip install -r requirements.txt
```

Install Playwright Chromium for browser fetch mode:

```bash
python -m playwright install --with-deps chromium
```

Start the app:

```bash
python app.py
```

## Health Checks

Check service health:

```bash
curl http://localhost/health
```

The endpoint returns:

- top-level scraper status.
- last cycle completion time and duration.
- motor count.
- per-provider status, job count, active jobs, queued jobs, blocked jobs, and
  block reasons.

During startup it returns `503` until the scraper leaves the `starting` state.

## Common Failure Modes

- No jobs loaded: check `config/jobs.yaml` and provider keys.
- Telegram warning at startup: expected when `config/telegram.yaml` is absent.
- Browser startup error: install Playwright browser dependencies.
- `browser_timeout`: increase `FETCH_TIMEOUT_SECONDS` or adjust
  `BROWSER_WAIT_SELECTOR`.
- `browser_blocked`: review provider block selectors and backoff settings.
- Provider concurrency: adjust `CONCURRENCY_LIMIT` in `config/motors.yaml`.
- Empty persisted results: check provider parser tests and source markup.

## Data Safety

Runtime JSON files live under `DATA_PATH`. The repository keeps `data/.gitignore`
so local scrape output is not committed. Treat files in `data/` as operational
state, not source code.

The tracked historical archive `data/data.zip` should be removed from tracking
only with explicit data cleanup approval.
