# Security

## Secrets

Telegram credentials belong only in `config/telegram.yaml`, which is ignored by
Git. Never commit real `api_token` or `chat_id` values.

Use the template:

```bash
cp config/telegram.yaml.example config/telegram.yaml
```

If credentials are missing, MLScraper disables notifications and continues
running.

## Runtime Data

Files under `data/` can contain product history and operational state. Treat
them as local runtime data. Do not commit scrape output.

## Scraping Safety

- Respect provider rate limits and backoff behavior.
- Keep concurrency conservative.
- Use browser mode only when needed.
- Do not bypass authentication or access controls.
- Review provider terms before using new targets.

## Reporting Issues

If you find a security issue, avoid posting secrets or sensitive runtime data in
public logs or issues. Share the minimum reproduction details needed to diagnose
the problem.
