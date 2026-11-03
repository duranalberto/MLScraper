# Data Model

MLScraper supports a **Hybrid In-Memory + Relational Database (MySQL / MariaDB)**
persistence architecture (`utils/db.py` and `shared/articles/catalog.py`) as well
as legacy per-search JSON file storage below `DATA_PATH` (`./data`).

## 1. Two-Tier Hybrid State Model

1. **Store-Global Canonical Catalog (`ProviderCatalog` in `shared/articles/catalog.py`)**:
   - Each store (`az`, `lv`, `ml`, `ph`) maintains a single Identity Map of
     canonical `Article` instances keyed by `(provider, identifier)` and backed
     by the `articles` table in MySQL.
   - All `Motor` searches within the same store hold references to the exact
     same canonical `Article` objects in RAM, preventing cross-search price or
     title divergence.
2. **Search-Scoped Membership (`Stream`s in `shared/articles/stream.py`)**:
   - Each `Motor` maintains fast indexed in-memory `active`, `on_hold`, and
     `finished` streams for its specific search query, backed by the
     `search_articles` join table in MySQL.

---

## 2. Relational Database Schema (8 Tables)

The relational schema is defined in `utils/db.py` (`MYSQL_SCHEMA_DDL`):

1. **`articles`**: Store-global canonical products keyed by `UNIQUE (provider, identifier)`.
   - Tracks `title`, `price`, `initial_price`, `lowest_price` (`+ lowest_price_at`),
     `highest_price` (`+ highest_price_at`), `url`, store-global `status`
     (`active | on_hold | finished`), `hold_misses`, `created_at`, `last_updated`,
     `last_fetched_epoch` (monotonic stale-page guard), and `version` (optimistic
     concurrency counter).
2. **`article_history`**: Price and title change history rows linked via
   `article_id` (`recorded_at`, `title`, `price`).
3. **`article_status_history`**: Store-global lifecycle transitions (`active` /
   `finished`) linked via `article_id`.
4. **`searches`**: Configured and historical search jobs keyed by
   `UNIQUE (provider, job_id)` and `UNIQUE (storage_path)`.
   - Stores `is_enabled` (`1` for active jobs in `config/jobs.yaml`, `0` for
     archived jobs), `is_first_run`, `query_text`, `resolved_url`,
     `filter_config` (JSON), `last_status`, `blocked_reason`, and `last_synced_at`.
5. **`search_articles`**: Many-to-many join table (`PRIMARY KEY (search_id, article_id)`)
   recording per-search `status`, `hold_misses`, `first_seen_at`, and `last_seen_at`.
6. **`notification_events`**: Persistent audit and deduplication log of alerts
   dispatched by `NotificationDispatcher` (`article_id`, `search_id`,
   `event_type`, `old_price`, `new_price`, `percent_change`, `observer_name`,
   `delivery_status`, `error_message`, `created_at`).
7. **`scrape_runs`**: Per-cycle execution telemetry and anti-bot block diagnostics
   (`search_id`, `provider`, `started_at`, `finished_at`, `duration_s`,
   `pages_fetched`, `scraped_count`, `new_count`, `updated_count`,
   `missing_count`, `status`, `error_reason`).
8. **`provider_url_cache`**: Persistent cache of resolved provider URL tokens
   (`PRIMARY KEY (provider, cache_key)`), used by `provider/liverpool/urls.py`
   to fall back to the last known valid encrypted segment if the live endpoint
   is unreachable at startup.

---

## 3. Article Record & Status Values

Each in-memory `Article` (`shared/articles/article.py`) exposes:

- `identifier`: stable store-native product identifier (`ASIN`, `MLM`, `SKU`).
- `title`: product title.
- `price`: current numeric product price.
- `initial_price`, `lowest_price`, `lowest_price_at`, `highest_price`,
  `highest_price_at`: historical price watermarks maintained automatically across
  updates even after `history` is truncated at `MAX_HISTORY = 100`.
- `datetime`: first-seen timestamp.
- `status`: lifecycle status (`Status` in `shared/articles/status.py`:
  `none`, `active`, `on_hold`, `finished`).
- `history` & `status_history`: prior title/price values and global status
  transitions, capped at `MAX_HISTORY = 100`.
- `hold_misses`: consecutive missing-item reconciliation counter.

### Strict Status Dominance Across Searches

When a product is tracked by multiple searches of the same store, its
store-global `articles.status` is computed from all enabled searches
(`searches.is_enabled = 1`) that track the product:

1. **`active`**: Product is `active` in at least one enabled search of the store.
2. **`on_hold`**: Product is not `active` in any enabled search, and is `on_hold`
   in at least one enabled search.
3. **`finished`**: Product has reached `finished` across all enabled searches
   that ever tracked it.
