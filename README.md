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

Run with Docker Compose:

```bash
docker compose up --build
```

The service listens on port `80` and exposes:

```text
GET /health
```

Run locally:

```bash
python -m pip install -r requirements.txt
python -m playwright install --with-deps chromium
python app.py
```

Run tests:

```bash
python -m unittest discover -v
```

Optional developer checks:

```bash
python -m pip install -r requirements-dev.txt
ruff check .
black --check .
pre-commit run --all-files
```

## Configuration

Runtime configuration lives in `config/`:

- `config/jobs.yaml` defines the scraping jobs to run.
- `config/motors.yaml` defines provider fetch, delay, backoff, and concurrency policy.
- `config/scrapper.yaml` defines scheduler-level defaults and backoff values.
- `config/telegram.yaml.example` is the template for optional Telegram credentials.

Copy the Telegram example only if you want notifications:

```bash
cp config/telegram.yaml.example config/telegram.yaml
```

`config/telegram.yaml` is ignored by Git and must never be committed.

By default, persisted product JSON is stored under `./data`. Docker Compose sets
`DATA_PATH=/MLScraper/data` inside the container and mounts the local `./data`
directory there.

See [Configuration](docs/CONFIGURATION.md) for the full config guide.

## Project Map

- `app.py` creates the FastAPI app and starts the background scraper task.
- `scrapper.py` schedules provider loops and routes notification events.
- `scraper/` contains shared article, stream, fetcher, and motor behavior.
- `provider/` contains provider-specific factories, parsers, and motors.
- `utils/` contains persistence, Telegram, headers, and supporting helpers.
- `tests/` contains the current regression suite.

More detail:

- [Architecture](docs/ARCHITECTURE.md)
- [Data Model](docs/DATA_MODEL.md)
- [Adding a Provider](docs/ADDING_PROVIDER.md)
- [Operations](docs/OPERATIONS.md)
- [Contributing](CONTRIBUTING.md)
- [Security](SECURITY.md)

## Working With LLM Agents

This repository includes root guidance files for coding agents:

- `AGENTS.md` for Codex
- `CLAUDE.md` for Claude

Both files tell agents how to work safely in this project: avoid changing
runtime data, keep provider-specific logic isolated, prefer existing registry
and factory patterns, and run the relevant checks after behavior changes.
