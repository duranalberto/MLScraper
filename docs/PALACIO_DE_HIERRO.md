# Palacio de Hierro

Palacio de Hierro jobs can build global search URLs or documented page routes
without storing a full URL in `config/jobs.yaml`. Explicit `url` values remain
the bypass for storefront routes and filters that have not been modeled.

## URL Rules

- `query` only: builds `https://www.elpalaciodehierro.com/buscar?q={slug}`.
- `page` only: builds the documented slash-delimited page route.
- `page` plus `brands`: appends an alphabetized brand path segment.
- `url`: bypasses generated URL rules and is used exactly as configured.

Palacio search queries are normalized to lowercase hyphenated slugs, so
`magic keyboard` becomes `buscar?q=magic-keyboard`.

Multiple brand filters are normalized, deduplicated, sorted alphabetically, and
joined with `|` before path encoding. For example, a `computo` page job with
`brands: [asus, apple]` builds:

```text
https://www.elpalaciodehierro.com/electronica/computadoras/apple%7Casus/
```

Global search plus a page, and global search plus brand filters without a page,
are rejected. Use an explicit `url` until the corresponding Palacio route shape
has been analyzed.

## Job Examples

```yaml
- provider: ph
  job_id: Magic Keyboard
  query: magic keyboard

- provider: ph
  job_id: Computadoras Apple Asus
  page: computo
  brands:
    - asus
    - apple
```

## Page Catalogue

| Page key | Breadcrumb | Generated path |
| --- | --- | --- |
| `electronica` | Electronica | `/electronica/` |
| `tablets` | Electronica > iPad y Tablet | `/electronica/tablets/` |
| `computo` | Electronica > Computo | `/electronica/computadoras/` |
| `laptops` | Electronica > Computo > Laptops | `/electronica/computadoras/laptops/` |
| `electrodomesticos` | Hogar > Electrodomesticos | `/hogar/electrodomesticos/` |
| `linea_blanca` | Hogar > Linea Blanca | `/hogar/linea-blanca/` |
| `refrigeradores` | Hogar > Linea Blanca > Refrigeradores | `/hogar/linea-blanca/refrigeradores/` |
| `videojuegos` | Videojuegos | `/videojuegos/` |
| `nintendo` | Videojuegos > Nintendo | `/videojuegos/nintendo/` |
| `playstation` | Videojuegos > PlayStation | `/videojuegos/playstation/` |

Page metadata keeps Palacio's route segments separate from storefront display
labels. That matters for pages such as `computo`, whose documented URL segment
is `computadoras`.
