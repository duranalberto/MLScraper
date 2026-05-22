# Amazon

Amazon jobs can build generated search URLs from query and documented
refinement fields. Explicit `url` values remain the bypass for browser-copied
URLs and refinements that have not been modeled.

## URL Rules

- `query`: builds `https://www.amazon.com.mx/s?k={query}`.
- seller only without `query`: builds a seller catalogue URL with only the
  seller `rh` refinement.
- `seller`: adds Amazon's seller `rh` refinement as `p_6:{seller_id}`.
- `brand`: adds Amazon's Marca `rh` refinement as `p_123:{brand_id}`.
- `seller` plus `brand`: joins refinements in one `rh` value with seller first.
- `url`: bypasses generated URL rules and is used exactly as configured.

Generated search text is lowercased and query encoded, so `Nintendo Switch 2`
becomes `k=nintendo+switch+2`. Generated URLs keep only canonical `k` and `rh`
parameters. Browser-copied extras such as `dc` belong in an explicit `url`.

## Job Examples

```yaml
- provider: az
  job_id: Macbook Amazon Mexico
  query: macbook
  seller: amazon_mx

- provider: az
  job_id: UGREEN seller catalogue
  seller: ugreen_group_limited

- provider: az
  job_id: Nintendo Switch 2
  query: nintendo switch 2
  brand: nintendo

- provider: az
  job_id: Apple Amazon Mexico
  query: apple
  seller: amazon_mx
  brand: apple
```

## Seller Catalogue

| Seller key | Seller | Seller refinement id |
| --- | --- | --- |
| `amazon_mx` | Amazon Mexico | `AVDBXBAVVSXLQ` |
| `amazon_usa` | Amazon USA | `A1G99GVHAT2WD8` |
| `amazon_remates` | Amazon Remates | `A23KQ2J0V65IPS` |
| `buyspry` | BuySPRY | `A37VHTD60S0G3C` |
| `randu_mx` | Randu MX | `A38E0DZZJWNMAA` |
| `v_i_v_o` | V-I-V-O | `AX105E1SOBX1B` |
| `ugreen_group_limited` | UGREEN GROUP LIMITED | `AKXVBT49GGF3B` |

`none` is accepted for seller configuration and omits the seller refinement.

## Marca Catalogue

| Brand key | Marca | Marca refinement id |
| --- | --- | --- |
| `apple` | Apple | `110955` |
| `nintendo` | Nintendo | `218247` |

## Documented Shapes

```text
https://www.amazon.com.mx/s?k=apple&rh=p_123%3A110955
https://www.amazon.com.mx/s?k=nintendo+switch+2&rh=p_123%3A218247
https://www.amazon.com.mx/s?k=apple&rh=p_6%3AAVDBXBAVVSXLQ%2Cp_123%3A110955
https://www.amazon.com.mx/s?rh=p_6%3AAKXVBT49GGF3B
```

Add new `brand` entries to `provider/amazon/options.py` only after their Marca
refinement ids have been documented and covered with offline URL tests.
