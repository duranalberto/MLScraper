# Contributing

Thanks for improving MLScraper. Keep changes small, testable, and aligned with
the existing provider/motor structure.

## Setup

For VS Code dev container development, rebuild and reopen the repository in the
container. The dev container image includes runtime dependencies, developer
tools, Playwright Chromium, and a Zsh terminal configured with Oh My Zsh,
Powerlevel10k, `zsh-autosuggestions`, and `zsh-syntax-highlighting`.

```bash
python -m pip install -r requirements.txt
python -m pip install -r requirements-dev.txt
python -m playwright install --with-deps chromium
```

For Docker-based development:

```bash
docker compose up --build
```

## Tests and Checks

Run the regression suite:

```bash
python -m unittest discover -v
```

Run optional developer checks:

```bash
ruff check .
black --check .
pre-commit run --all-files
```

## Style

- Prefer clear, direct Python over new abstractions.
- Keep provider-specific parsing inside provider packages.
- Put shared scraper lifecycle behavior in `scraper/`.
- Use the existing registry and factory pattern for providers.
- Update docs when commands, config, providers, or runtime behavior change.

## Pull Request Checklist

- Tests were run or skipped with a reason.
- Config changes are documented.
- New providers include parser tests.
- `config/telegram.yaml` and runtime files under `data/` are not committed.
- README or docs are updated for user-visible changes.
