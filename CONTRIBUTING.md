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

## Tests and Checks

Run the regression suite:

```bash
python -m unittest discover -v
```

Run optional developer checks:

```bash
pyright
ruff check .
black --check .
pre-commit run --all-files
```

## Style

- Prefer clear, direct Python over new abstractions.
- Keep provider-specific parsing, URL building, options/enums, and selectors
  inside provider packages.
- Put shared provider/scraper contracts in `shared/`.
- Put scraper job assembly and runtime orchestration in `scraper/`.
- Use the registry and factory pattern in `scraper/jobs/` for providers.
- Avoid new generic provider `utils.py` modules; use purpose-specific names.
- Update docs when commands, config, providers, or runtime behavior change.

## Documentation and Docstrings

Use Google-style docstrings for project documentation. Docstrings are currently
a contributor convention, not a lint-enforced requirement; do not add docstring
linting until the existing public API has been documented.

Required docstrings:

- Public modules that define important behavior.
- Public classes.
- Public functions and methods.
- Abstract methods and provider contracts such as `Motor.scrape_page`.
- Factory, loader, parser, fetcher, persistence, notification, and orchestration
  functions whose behavior is not obvious from the name.

Optional docstrings:

- Simple private helpers where the name and type hints are enough.
- Dunder methods with standard behavior.
- Test fakes and one-off test helpers unless they encode important behavior.

Docstrings should explain meaning, constraints, side effects, and failure
behavior. Keep type information in annotations instead of repeating it in prose.
Avoid docstrings that merely restate the function name.

Use these Google-style sections when relevant:

- `Args:` for non-obvious parameters.
- `Returns:` for returned values, including tuple meanings.
- `Raises:` only for exceptions intentionally raised by the function.
- `Side Effects:` for file writes, network calls, Telegram sends, mutation of
  streams, or scheduler state.
- `Notes:` for scraper-specific assumptions such as expected HTML shape,
  pagination behavior, retry semantics, or config precedence.

For async functions, mention awaited network, file, scheduler, or notification
side effects when relevant. For provider parsers, document the expected input
shape and returned item fields. For functions that swallow errors and return
fallback values, document the fallback behavior instead of listing a `Raises:`
section.

Example:

```python
def scrape_page(self, body: dict) -> tuple[list[dict], str | None]:
    """Parse a provider search page into product records and pagination state.

    Args:
        body: Mapping with ``content`` containing the fetched HTML and ``url``
            containing the current page URL.

    Returns:
        A tuple of ``(items, next_url)``. Each item must include
        ``identifier``, ``title``, and ``price``. ``next_url`` is ``None`` when
        there are no more pages.

    Raises:
        ValueError: If the page contains a known provider payload but the
            payload is malformed.

    Notes:
        Return an empty item list only when the page is genuinely empty. Blocked,
        gated, or incomplete pages should be reported through the provider's
        existing blocked-page behavior so reconciliation is not triggered.
    """
```

## Pull Request Checklist

- Tests were run or skipped with a reason.
- Config changes are documented.
- New providers include parser tests.
- `config/telegram.yaml` and runtime files under `data/` are not committed.
- README or docs are updated for user-visible changes.
