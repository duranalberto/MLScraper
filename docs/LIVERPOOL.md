# Liverpool

Liverpool jobs generated from structured fields must filter products to
Liverpool as seller. Marketplace sellers are allowed only when a job provides an
explicit `url`, because explicit URLs are used unchanged.

## URL Rules

- `query` only: resolves and builds a global seller-filtered search URL.
- `page` only: resolves and builds the seller-filtered URL for that page.
- `page` plus `query`: builds `https://www.liverpool.com.mx/tienda/N-{page_token}?s={query}`.
- `url`: bypasses all generated URL rules and is used exactly as configured.
- `category`: legacy alias for `page`; conflicting `page` and `category` values are rejected.

The root-token page + query shape is intentional. Validation showed that
appending `?s=` to the slugged seller URL can drop the selected page and seller
refinements, while `/tienda/N-{page_token}?s=query` preserves both.

## Seller Resolution

Generated Liverpool URLs call Liverpool's `/getPlpFilter` endpoint with the
documented page metadata and the seller refinement:

```text
categoryId: the page category id
Path: PLP
label: variants.sellernames
Fs: liverpool
displayName: Vendido por
orValue: true
```

The resolver uses `mainContent.originalRequest.encryptedFullUrl` and validates
that `selectedNavigation` contains `variants.sellernames = liverpool`. Page
URLs also require `ancestors = the page category id`. If Liverpool does not
return a valid seller-filtered route, generated jobs fail fast and the job must
provide an explicit `url`.

The full `N-` tokens are still opaque. Tests should validate generated URLs
against known-good seller-filtered URLs, but page metadata should not store the
tokens.

## Page Catalogue

| Page key | Kind | Breadcrumb | Canonical URL | Liverpool seller URL |
| --- | --- | --- | --- | --- |
| `linea_blanca_y_electrodomesticos` | Landing | Home > Línea Blanca y Electrodomésticos | `https://www.liverpool.com.mx/tienda/l%C3%ADnea-blanca-y-electrodom%C3%A9sticos/catst42832389` | `https://www.liverpool.com.mx/tienda/l%C3%ADnea-blanca-y-electrodom%C3%A9sticos/N-S1sLjNksKoG%2BC2c1SDPsHKIBKNV9C39qzAQKlWKyNPun2aJSsdu2MIlSvIBK7fjU` |
| `electrodomesticos_de_cocina` | Landing | Home > Línea Blanca y Electrodomésticos > Electrodomésticos de Cocina | `https://www.liverpool.com.mx/tienda/electrodom%C3%A9sticos-de-cocina/catst42832953` | `https://www.liverpool.com.mx/tienda/electrodom%C3%A9sticos-de-cocina/N-S1sLjNksKoG%2BC2c1SDPsHE2WJgzT1N18wn6bm3Crd%2BLSeXXyPBbJePl81tX2VT0v` |
| `cafeteras_y_molinos` | Products | Home > Línea Blanca y Electrodomésticos > Electrodomésticos de Cocina > Cafeteras y Molinos | `https://www.liverpool.com.mx/tienda/cafeteras-y-molinos/catst42843585` | `https://www.liverpool.com.mx/tienda/cafeteras-y-molinos/N-S1sLjNksKoG%2BC2c1SDPsHMGMg%2BPbTviv0GV7AiYl%2FeJFejoKIubh5lKg%2Bkb6zYFt` |
| `licuadoras` | Products | Home > Línea Blanca y Electrodomésticos > Electrodomésticos de Cocina > Licuadoras | `https://www.liverpool.com.mx/tienda/licuadoras/catst42843581` | `https://www.liverpool.com.mx/tienda/licuadoras/N-S1sLjNksKoG%2BC2c1SDPsHMGMg%2BPbTviv0GV7AiYl%2FeIkA6zlzIoCxRcW4yIc40do` |
| `freidoras` | Products | Home > Línea Blanca y Electrodomésticos > Electrodomésticos de Cocina > Freidoras | `https://www.liverpool.com.mx/tienda/freidoras/catst42843539` | `https://www.liverpool.com.mx/tienda/freidoras/N-S1sLjNksKoG%2BC2c1SDPsHMGMg%2BPbTviv0GV7AiYl%2FeKspjSgk5Q4M8QBwce7ym1W` |
| `hornos_de_microondas` | Products | Home > Línea Blanca y Electrodomésticos > Electrodomésticos de Cocina > Hornos de Microondas | `https://www.liverpool.com.mx/tienda/hornos-de-microondas/catst42843550` | `https://www.liverpool.com.mx/tienda/hornos-de-microondas/N-S1sLjNksKoG%2BC2c1SDPsHMGMg%2BPbTviv0GV7AiYl%2FeJ8uFaOgGrsNu3LQpmx2RfW` |
| `hornos_electricos` | Products | Home > Línea Blanca y Electrodomésticos > Electrodomésticos de Cocina > Hornos Eléctricos | `https://www.liverpool.com.mx/tienda/hornos-el%C3%A9ctricos/catst53843927` | `https://www.liverpool.com.mx/tienda/hornos-el%C3%A9ctricos/N-S1sLjNksKoG%2BC2c1SDPsHDLkL1UcSQDvtOqhAagDbUKyQ4wGi88mGsyxG1aD%2B3uQ` |
| `computacion` | Landing | Home > Electrónica > Computación | `https://www.liverpool.com.mx/tienda/computaci%C3%B3n/cat3410055` | `https://www.liverpool.com.mx/tienda/computaci%C3%B3n/N-S1sLjNksKoG%2BC2c1SDPsHN%2BJ%2BVnTTvZIur1XfBh58ds%3D` |
| `laptops` | Products | Home > Electrónica > Computación > Laptops | `https://www.liverpool.com.mx/tienda/laptops/catst10075558` | `https://www.liverpool.com.mx/tienda/laptops/N-S1sLjNksKoG%2BC2c1SDPsHADb51HPoq41uykVTx%2F8p7q4Lv5kmJ%2FB7n9SHDZAiZOr` |
| `tablets` | Products | Home > Electrónica > Computación > Tablets | `https://www.liverpool.com.mx/tienda/tablets/cat580066` | `https://www.liverpool.com.mx/tienda/tablets/N-S1sLjNksKoG%2BC2c1SDPsHLBjV%2BmEL2zQn91638D96w4%3D` |
| `accesorios_computacion` | Products | Home > Electrónica > Computación > Accesorios Computación | `https://www.liverpool.com.mx/tienda/accesorios-computaci%C3%B3n/cat670053` | `https://www.liverpool.com.mx/tienda/accesorios-computaci%C3%B3n/N-S1sLjNksKoG%2BC2c1SDPsHPyN7Zg7IIn7KTQOnaUXA84%3D` |
| `videojuegos` | Landing | Home > Videojuegos | `https://www.liverpool.com.mx/tienda/videojuegos/cat670055` | `https://www.liverpool.com.mx/tienda/videojuegos/N-S1sLjNksKoG%2BC2c1SDPsHHgKKoxCWs4ssLitZ2y5bdQ%3D` |
| `nintendo` | Landing | Home > Videojuegos > Nintendo | `https://www.liverpool.com.mx/tienda/nintendo/cat5030010` | `https://www.liverpool.com.mx/tienda/nintendo/N-S1sLjNksKoG%2BC2c1SDPsHKoOUK876ftr4S1vpt6rlqU%3D` |
| `consolas_nintendo` | Products | Home > Videojuegos > Nintendo > Consolas Nintendo | `https://www.liverpool.com.mx/tienda/consolas-nintendo/catst16854843` | `https://www.liverpool.com.mx/tienda/consolas-nintendo/N-S1sLjNksKoG%2BC2c1SDPsHMZu13evjQvlZwcij64vMMV4Z%2ByNx1qLg8geatR3xCA5` |
| `juegos_nintendo` | Products | Home > Videojuegos > Nintendo > Juegos Nintendo | `https://www.liverpool.com.mx/tienda/juegos-nintendo/catst14539980` | `https://www.liverpool.com.mx/tienda/juegos-nintendo/N-S1sLjNksKoG%2BC2c1SDPsHEMtiDHLusAuxLK0y30fWRU5PhnhiYjJElHuz9EseRgf` |
| `controles_nintendo` | Products | Home > Videojuegos > Nintendo > Controles Nintendo | `https://www.liverpool.com.mx/tienda/controles-nintendo/catst20605695` | `https://www.liverpool.com.mx/tienda/controles-nintendo/N-S1sLjNksKoG%2BC2c1SDPsHCsVwygWvVuPuIw9xarBO8VTKv41DLyvSQbEdA8sg1qy` |
| `apple` | Landing | Home > Apple | `https://www.liverpool.com.mx/tienda/apple/catst2145072` | `https://www.liverpool.com.mx/tienda/apple/N-S1sLjNksKoG%2BC2c1SDPsHNm0puD%2BxMdUs8fFWfZr2VPe%2F6v1sCWzDBDSulA990d4` |

## `?showPLP`

Appending `?showPLP` to a landing page can expose its product listing and is
useful for validating breadcrumbs and child pages. It is not seller-filtered by
itself, so generated scrape URLs still resolve the Liverpool seller filter
through `/getPlpFilter`.

## Adding A Page

1. Capture the canonical URL, page name, breadcrumb, slug, and category id.
2. Confirm `/getPlpFilter` can resolve a Liverpool-seller URL for that page.
3. Confirm the resolver response selected navigation contains
   `variants.sellernames = liverpool`.
4. Confirm the selected `ancestors` refinement matches the page category id.
5. Add the page metadata to `Page` in `provider/liverpool/options.py`, including aliases
   only when they cannot collide with another page.
6. Add or update URL and hierarchy tests in `tests/test_provider_parsers.py`
   using a known-good seller-filtered URL fixture.
7. Add the documented canonical and known-good seller URL to this file.

## Validation Recipe

Use a browser-like request to `/getPlpFilter`, parse the JSON, and inspect:

```text
mainContent.originalRequest.encryptedFullUrl
mainContent.selectedNavigation
```

The expected selected navigation for generated scrape URLs is:

```text
variants.sellernames -> liverpool
ancestors -> the page category id
```

If either value is missing, keep the page out of generated configuration and
use an explicit `url` until Liverpool returns a valid resolver response.
