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
python -m pip install -r requirements.txt
python -m playwright install --with-deps chromium
python app.py
```

The service listens on port `80` and exposes:

```text
GET /health
```

Run tests:

```bash
python -m unittest discover -v
```

Optional developer checks:

```bash
python -m pip install -r requirements-dev.txt
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

See [Configuration](docs/CONFIGURATION.md) for the full config guide.

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
