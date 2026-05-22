# Mercado Libre

Mercado Libre jobs can build global listing URLs or known seller-store listing
URLs from structured `config/jobs.yaml` fields. Explicit `url` values remain
the bypass for sellers, categories, and filter combinations that have not been
modeled.

## URL Rules

- no `seller`: builds a global listing URL and requires `query`.
- global `category`: prefixes the documented category path.
- global `state`: inserts `nuevo` or `usado` after the category path when one
  exists, or before the query when no category is configured.
- `seller` only: builds the seller all-products listing URL.
- `seller` plus `query`: appends the slugged query to the seller listing path.
- `seller` plus `category`: inserts `listado` and the full category path.
- seller category routes can add `state` and then an optional query slug.
- `url`: bypasses generated URL rules and is used exactly as configured.

Global queries end with Mercado Libre's `_NoIndex_True` suffix. Store query
routes do not add that suffix. Query slugs are lowercase ASCII text separated
with hyphens, so `Nintendo 3DS` becomes `nintendo-3ds`.

Generated seller routes reject `state` without a category because that route
shape is not part of the initial documented catalogue.

## Job Examples

```yaml
- provider: ml
  job_id: Nintendo 3DS
  query: nintendo 3ds
  category: consolas_videojuegos
  state: usado

- provider: ml
  job_id: Apple iPad Pro
  seller: apple
  query: ipad pro 13

- provider: ml
  job_id: Nintendo videojuegos
  seller: nintendo
  category: videojuegos
```

## Seller Catalogue

| Seller key | Store | Landing reference | Listing path |
| --- | --- | --- | --- |
| `apple` | Apple | `https://www.mercadolibre.com.mx/tienda/apple` | `/tienda/apple/` |
| `nintendo` | Nintendo | `https://www.mercadolibre.com.mx/tienda/nintendo` | `/tienda/nintendo/` |

## Category Catalogue

| Category key | Breadcrumb | Listing path |
| --- | --- | --- |
| `computacion` | Computacion | `/computacion/` |
| `celulares_telefonia` | Celulares y Telefonia | `/celulares-telefonia/` |
| `consolas_videojuegos` | Consolas y Videojuegos | `/consolas-videojuegos/` |
| `consolas` | Consolas y Videojuegos > Consolas | `/consolas-videojuegos/consolas/` |
| `videojuegos` | Consolas y Videojuegos > Videojuegos | `/consolas-videojuegos/videojuegos/` |

## Documented Shapes

```text
https://listado.mercadolibre.com.mx/consolas-videojuegos/usado/nintendo-3ds_NoIndex_True
https://listado.mercadolibre.com.mx/tienda/apple/listado/computacion/
https://listado.mercadolibre.com.mx/tienda/nintendo/pokemon
```

Add sellers and categories to `provider/mercado_libre/options.py` only after
their route paths have been documented and covered with offline URL tests.
