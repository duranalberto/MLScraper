# Adding a Provider

Follow the existing registry and motor pattern. Keep provider-specific parsing
inside the new provider package.

## Steps

1. Create a provider package under `provider/<provider_name>/`.
2. Add a motor class that subclasses `scraper.motor.Motor`.
3. Set `PROVIDER_KEY` on the motor.
4. Implement `scrape_page(self, body)` and return `(items, next_url)`.
5. Register a factory in `provider/factories.py` with a short provider key.
6. Add any enum coercion needed by YAML jobs in `provider/loader.py`.
7. Add default or provider-specific policy in `config/motors.yaml`.
8. Add a safe example job to `config/jobs.yaml.example`.
9. Add parser and configuration tests in `tests/`.
10. Update `README.md` and `docs/CONFIGURATION.md` if the public setup changes.

## Motor Contract

`scrape_page` receives:

```python
{"content": html, "url": current_url}
```

It should return:

```python
([{"identifier": "...", "title": "...", "price": 123.45, "url": "..."}], next_url)
```

`next_url` should be `None` when there is no next page.

Required item fields:

- `identifier`
- `title`
- `price`

Optional item fields:

- `url`

## Storage Paths

Factories build relative paths below `DATA_PATH`. Use stable, descriptive paths
grouped by provider:

```text
provider_name/search-term.json
provider_name/search-term__qualifier.json
```

Do not let job input produce absolute paths or parent-directory traversal.

## Tests

At minimum, add tests for:

- Factory construction.
- Job loader coercion or validation if new job fields need it.
- Parser behavior using a small HTML or JSON fixture string.
- Pagination URL behavior.
- Empty or gated pages when the provider has known block modes.

Run:

```bash
python -m unittest discover -v
```
