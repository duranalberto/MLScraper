from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from bs4 import BeautifulSoup

from provider.amazon.motor import Amazon
from provider.amazon.options import Brand as AmazonBrand
from provider.amazon.options import Seller as AmazonSeller
from provider.amazon.urls import build_amazon_url, build_search_url, preview_amazon_url
from provider.liverpool import urls as lv_urls
from provider.liverpool.motor import Liverpool
from provider.liverpool.options import (
    LIVERPOOL_SELLER_FILTER_ID,
    LIVERPOOL_SELLER_REFINEMENT_NAME,
    LIVERPOOL_SELLER_REFINEMENT_VALUE,
    Page as LiverpoolPage,
    resolve_page,
    resolve_page_path,
)
from provider.liverpool.urls import (
    append_page_segment,
    build_canonical_page_url,
    build_liverpool_url,
    build_page_url,
    build_zapatos_talla_url,
    current_page_number,
    preview_liverpool_url,
)
from provider.mercado_libre import parser as ml_parser
from provider.mercado_libre.options import Category
from provider.mercado_libre.options import Seller as MercadoLibreSeller
from provider.mercado_libre.options import State
from provider.mercado_libre.urls import (
    build_global_search_url,
    build_mercado_libre_url,
    build_store_url,
    get_identifier,
    preview_mercado_libre_url,
)
from provider.palacio_de_hierro.motor import PalacioDeHierro
from provider.palacio_de_hierro.options import Page as PalacioPage
from provider.palacio_de_hierro.options import resolve_page as resolve_palacio_page
from provider.palacio_de_hierro.urls import (
    build_page_url as build_palacio_page_url,
    build_palacio_url,
    build_search_url as build_palacio_search_url,
    preview_palacio_url,
)
from tests.helpers import empty_article_storage


class AmazonUrlTests(unittest.TestCase):
    def test_generated_search_urls_follow_documented_refinement_shapes(self) -> None:
        self.assertEqual(
            build_amazon_url(query="MacBook Air"),
            "https://www.amazon.com.mx/s?k=macbook+air",
        )
        self.assertEqual(
            build_amazon_url(query="Apple"),
            "https://www.amazon.com.mx/s?k=apple",
        )
        self.assertEqual(
            build_search_url("Apple", seller=AmazonSeller.amazon_mx),
            "https://www.amazon.com.mx/s?k=apple&rh=p_6%3AAVDBXBAVVSXLQ",
        )
        new_sellers = {
            "randu_mx": "A38E0DZZJWNMAA",
            "v_i_v_o": "AX105E1SOBX1B",
            "ugreen_group_limited": "AKXVBT49GGF3B",
        }
        for seller, identifier in new_sellers.items():
            with self.subTest(seller=seller):
                self.assertEqual(
                    build_amazon_url(seller=seller),
                    "https://www.amazon.com.mx/s?rh=p_6%3A" + identifier,
                )
        self.assertEqual(
            build_search_url("Apple", brand=AmazonBrand.apple),
            "https://www.amazon.com.mx/s?k=apple&rh=p_123%3A110955",
        )
        self.assertEqual(
            build_search_url("Nintendo Switch 2", brand=AmazonBrand.nintendo),
            "https://www.amazon.com.mx/s?k=nintendo+switch+2&rh=p_123%3A218247",
        )
        self.assertEqual(
            build_search_url("Apple", seller="amazon_mx", brand="apple"),
            "https://www.amazon.com.mx/s?k=apple&rh=" "p_6%3AAVDBXBAVVSXLQ%2Cp_123%3A110955",
        )

    def test_preview_explicit_url_wins_over_structured_fields(self) -> None:
        self.assertEqual(
            preview_amazon_url(
                url="https://example.test/custom",
                query="ignored",
                seller=AmazonSeller.amazon_mx,
                brand=AmazonBrand.apple,
            ),
            "https://example.test/custom",
        )
        self.assertEqual(
            preview_amazon_url(seller=AmazonSeller.ugreen_group_limited),
            "https://www.amazon.com.mx/s?rh=p_6%3AAKXVBT49GGF3B",
        )

    def test_unknown_builder_options_fail_fast(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unknown Amazon seller"):
            build_search_url("apple", seller="missing")
        with self.assertRaisesRegex(ValueError, "Unknown Amazon brand"):
            build_search_url("apple", brand="missing")


class MercadoLibreUrlTests(unittest.TestCase):
    def test_get_identifier_prefers_wid_then_product_ids(self) -> None:
        self.assertEqual(get_identifier("https://example.test/item?wid=MLM123"), "MLM123")
        self.assertEqual(get_identifier("https://example.test/up/MLMU123"), "MLMU123")
        self.assertEqual(get_identifier("https://example.test/p/MLM999"), "MLM999")

    def test_global_search_urls_follow_documented_filter_order(self) -> None:
        self.assertEqual(
            build_global_search_url("Nintendo 3DS", category=Category.consolas_videojuegos),
            "https://listado.mercadolibre.com.mx/" "consolas-videojuegos/nintendo-3ds_NoIndex_True",
        )
        self.assertEqual(
            build_global_search_url(
                "Nintendo 3DS",
                category=Category.consolas_videojuegos,
                state=State.nuevo,
            ),
            "https://listado.mercadolibre.com.mx/"
            "consolas-videojuegos/nuevo/nintendo-3ds_NoIndex_True",
        )
        self.assertEqual(
            build_global_search_url(
                "Nintendo 3DS",
                category=Category.consolas_videojuegos,
                state=State.usado,
            ),
            "https://listado.mercadolibre.com.mx/"
            "consolas-videojuegos/usado/nintendo-3ds_NoIndex_True",
        )
        self.assertEqual(
            build_global_search_url("Nintendo 3DS", category=Category.consolas, state=State.usado),
            "https://listado.mercadolibre.com.mx/"
            "consolas-videojuegos/consolas/usado/nintendo-3ds_NoIndex_True",
        )
        self.assertEqual(
            build_global_search_url(
                "Nintendo 3DS",
                category=Category.videojuegos,
                state=State.nuevo,
            ),
            "https://listado.mercadolibre.com.mx/"
            "consolas-videojuegos/videojuegos/nuevo/nintendo-3ds_NoIndex_True",
        )

    def test_store_urls_follow_documented_seller_routes(self) -> None:
        self.assertEqual(
            build_store_url(MercadoLibreSeller.apple),
            "https://listado.mercadolibre.com.mx/tienda/apple/",
        )
        self.assertEqual(
            build_store_url(MercadoLibreSeller.apple, category=Category.computacion),
            "https://listado.mercadolibre.com.mx/tienda/apple/listado/computacion/",
        )
        self.assertEqual(
            build_store_url(MercadoLibreSeller.apple, category=Category.celulares_telefonia),
            "https://listado.mercadolibre.com.mx/tienda/apple/listado/celulares-telefonia/",
        )
        self.assertEqual(
            build_store_url(MercadoLibreSeller.apple, query="iPad Pro 13"),
            "https://listado.mercadolibre.com.mx/tienda/apple/ipad-pro-13",
        )
        self.assertEqual(
            build_store_url(MercadoLibreSeller.nintendo, category=Category.videojuegos),
            "https://listado.mercadolibre.com.mx/"
            "tienda/nintendo/listado/consolas-videojuegos/videojuegos/",
        )
        self.assertEqual(
            build_store_url(
                MercadoLibreSeller.nintendo,
                query="Pokemon",
                category=Category.videojuegos,
                state=State.usado,
            ),
            "https://listado.mercadolibre.com.mx/"
            "tienda/nintendo/listado/consolas-videojuegos/videojuegos/usado/pokemon",
        )
        self.assertEqual(
            build_store_url(MercadoLibreSeller.nintendo, query="pokemon"),
            "https://listado.mercadolibre.com.mx/tienda/nintendo/pokemon",
        )

    def test_generated_url_uses_explicit_global_query_and_preview_passthrough(self) -> None:
        self.assertEqual(
            build_mercado_libre_url(query="Nintendo 3DS"),
            "https://listado.mercadolibre.com.mx/nintendo-3ds_NoIndex_True",
        )
        self.assertEqual(
            build_mercado_libre_url(
                query="Nintendo 3DS",
                category=Category.consolas_videojuegos,
            ),
            "https://listado.mercadolibre.com.mx/" "consolas-videojuegos/nintendo-3ds_NoIndex_True",
        )
        self.assertEqual(
            preview_mercado_libre_url(
                url="https://example.test/custom",
                seller=MercadoLibreSeller.apple,
            ),
            "https://example.test/custom",
        )

    def test_store_state_without_category_requires_explicit_url(self) -> None:
        with self.assertRaisesRegex(ValueError, "state filters require a category"):
            build_store_url(MercadoLibreSeller.apple, state=State.usado)


class MercadoLibrePaginationTests(unittest.TestCase):
    def test_pagination_respects_total_results_limit(self) -> None:
        soup = BeautifulSoup(
            """
            <span>60 resultados</span>
            <li class="andes-pagination__button--next">
              <a title="Siguiente" href="#">Next</a>
            </li>
            """,
            "html.parser",
        )

        self.assertIsNone(
            ml_parser.pagination_next_url(
                "https://listado.mercadolibre.com.mx/test_Desde_49_NoIndex_True",
                items_on_page=12,
                page_size=48,
                soup=soup,
            )
        )

    def test_inject_offset_handles_special_url_shapes(self) -> None:
        self.assertEqual(
            ml_parser.inject_offset(
                "https://listado.mercadolibre.com.mx/test_Desde_49_NoIndex_True",
                97,
            ),
            "https://listado.mercadolibre.com.mx/test_Desde_97_NoIndex_True",
        )
        self.assertEqual(
            ml_parser.inject_offset(
                "https://listado.mercadolibre.com.mx/_CustId_123_NoIndex_True",
                49,
            ),
            "https://listado.mercadolibre.com.mx/_Desde_49_CustId_123_NoIndex_True",
        )


class LiverpoolUrlTests(unittest.TestCase):
    known_seller_urls = {
        LiverpoolPage.linea_blanca_y_electrodomesticos: (
            "https://www.liverpool.com.mx/tienda/catst42832389/"
            "N-S1sLjNksKoG%2BC2c1SDPsHKIBKNV9C39qzAQKlWKyNPun2aJSsdu2MIlSvIBK7fjU?showPLP"
        ),
        LiverpoolPage.electrodomesticos_de_cocina: (
            "https://www.liverpool.com.mx/tienda/catst42832953/"
            "N-S1sLjNksKoG%2BC2c1SDPsHE2WJgzT1N18wn6bm3Crd%2BLSeXXyPBbJePl81tX2VT0v?showPLP"
        ),
        LiverpoolPage.hornos_electricos: (
            "https://www.liverpool.com.mx/tienda/catst53843927/"
            "N-S1sLjNksKoG%2BC2c1SDPsHDLkL1UcSQDvtOqhAagDbUKyQ4wGi88mGsyxG1aD%2B3uQ"
        ),
        LiverpoolPage.computacion: (
            "https://www.liverpool.com.mx/tienda/cat3410055/"
            "N-S1sLjNksKoG%2BC2c1SDPsHN%2BJ%2BVnTTvZIur1XfBh58ds%3D?showPLP"
        ),
        LiverpoolPage.laptops: (
            "https://www.liverpool.com.mx/tienda/catst10075558/"
            "N-S1sLjNksKoG%2BC2c1SDPsHADb51HPoq41uykVTx%2F8p7q4Lv5kmJ%2FB7n9SHDZAiZOr"
        ),
        LiverpoolPage.videojuegos: (
            "https://www.liverpool.com.mx/tienda/cat670055/"
            "N-S1sLjNksKoG%2BC2c1SDPsHHgKKoxCWs4ssLitZ2y5bdQ%3D?showPLP"
        ),
        LiverpoolPage.nintendo: (
            "https://www.liverpool.com.mx/tienda/cat5030010/"
            "N-S1sLjNksKoG%2BC2c1SDPsHKoOUK876ftr4S1vpt6rlqU%3D?showPLP"
        ),
        LiverpoolPage.juegos_nintendo: (
            "https://www.liverpool.com.mx/tienda/catst14539980/"
            "N-S1sLjNksKoG%2BC2c1SDPsHEMtiDHLusAuxLK0y30fWRU5PhnhiYjJElHuz9EseRgf"
        ),
        LiverpoolPage.apple: (
            "https://www.liverpool.com.mx/tienda/catst2145072/"
            "N-S1sLjNksKoG%2BC2c1SDPsHNm0puD%2BxMdUs8fFWfZr2VPe%2F6v1sCWzDBDSulA990d4?showPLP"
        ),
    }

    def setUp(self) -> None:
        lv_urls._resolve_seller_filtered_segment.cache_clear()

    def tearDown(self) -> None:
        lv_urls._resolve_seller_filtered_segment.cache_clear()

    class _MockResponse:
        def __init__(self, payload: dict) -> None:
            self.payload = payload

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return self.payload

    def _seller_payload(self, encrypted_url: str, page: LiverpoolPage | None = None) -> dict:
        filters_groups = [
            {
                "name": "Vendido por",
                "dimensionName": LIVERPOOL_SELLER_REFINEMENT_NAME,
                "filter": [
                    {
                        "label": LIVERPOOL_SELLER_REFINEMENT_VALUE,
                        "filterId": LIVERPOOL_SELLER_FILTER_ID,
                        "selected": True,
                    }
                ],
            }
        ]
        filter_parts = [
            'attributes.productSiteIds: ANY("liverpool")',
            f'attributes.sellernames: ANY("{LIVERPOOL_SELLER_REFINEMENT_VALUE}")',
        ]
        if page is not None:
            filters_groups.append(
                {
                    "name": "Categoría",
                    "dimensionName": "Category",
                    "ancestors": [
                        {
                            "label": page.value.display_name,
                            "categoryId": page.value.category_id.lower(),
                            "selected": True,
                        }
                    ],
                    "filter": [],
                }
            )
            filter_parts.append(f'attributes.ancestors: ANY("{page.value.category_id}")')

        return {
            "data": {
                "encryptedFilters": encrypted_url,
                "filter": " AND ".join(filter_parts),
                "filtersGroups": filters_groups,
            }
        }

    def _mock_seller_url(self, encrypted_url: str, page: LiverpoolPage | None = None):
        return patch(
            "provider.liverpool.urls.requests.post",
            return_value=self._MockResponse(self._seller_payload(encrypted_url, page)),
        )

    def _segment_for_page(self, page: LiverpoolPage) -> str:
        return self.known_seller_urls[page].rsplit("/", 1)[-1].split("?", 1)[0]

    def test_generated_search_url_uses_verified_liverpool_seller_resolver(self) -> None:
        encrypted_url = "N-8BAqotJ%2FHmg946pY%2BECjww%3D%3D?s=ventilador"
        with self._mock_seller_url(encrypted_url) as resolver:
            self.assertEqual(
                build_liverpool_url(query="ventilador"),
                "https://www.liverpool.com.mx/tienda/"
                "N-8BAqotJ%2FHmg946pY%2BECjww%3D%3D?s=ventilador",
            )

        body = resolver.call_args.kwargs["json"]
        self.assertEqual(body["query"], "ventilador")
        self.assertEqual(body["appliedFilters"], [LIVERPOOL_SELLER_FILTER_ID])

    def test_search_routes_require_explicit_liverpool_query(self) -> None:
        with self.assertRaisesRegex(ValueError, "search query cannot be blank"):
            build_liverpool_url()

    def test_generated_brand_filter_requires_explicit_url(self) -> None:
        with self.assertRaisesRegex(ValueError, "brand filters require an explicit url"):
            build_liverpool_url(brand="lg")

    def test_generated_page_url_uses_resolved_seller_segment(self) -> None:
        with self._mock_seller_url(
            self._segment_for_page(LiverpoolPage.hornos_electricos),
            LiverpoolPage.hornos_electricos,
        ) as resolver:
            self.assertEqual(
                build_liverpool_url(page=LiverpoolPage.hornos_electricos),
                self.known_seller_urls[LiverpoolPage.hornos_electricos],
            )

        body = resolver.call_args.kwargs["json"]
        self.assertEqual(body["categoryId"], "catst53843927")
        self.assertNotIn("query", body)

    def test_generated_page_query_uses_root_token_form(self) -> None:
        with self._mock_seller_url(
            self._segment_for_page(LiverpoolPage.hornos_electricos),
            LiverpoolPage.hornos_electricos,
        ):
            self.assertEqual(
                build_liverpool_url(page=LiverpoolPage.hornos_electricos, query="black"),
                "https://www.liverpool.com.mx/tienda/"
                "N-S1sLjNksKoG%2BC2c1SDPsHDLkL1UcSQDvtOqhAagDbUKyQ4wGi88mGsyxG1aD%2B3uQ?s=black",
            )

    def test_known_seller_pages_build_exact_urls_from_resolver_tokens(self) -> None:
        self.assertEqual(LIVERPOOL_SELLER_REFINEMENT_NAME, "variants.sellernames")
        self.assertEqual(LIVERPOOL_SELLER_REFINEMENT_VALUE, "liverpool")
        for page, expected_url in self.known_seller_urls.items():
            with self.subTest(page=page.name):
                with self._mock_seller_url(self._segment_for_page(page), page):
                    self.assertEqual(build_page_url(page), expected_url)

    def test_landing_pages_build_exact_seller_urls_from_verified_fixtures(self) -> None:
        for page in (
            LiverpoolPage.linea_blanca_y_electrodomesticos,
            LiverpoolPage.computacion,
            LiverpoolPage.videojuegos,
        ):
            with self.subTest(page=page.name):
                with self._mock_seller_url(self._segment_for_page(page), page):
                    self.assertEqual(
                        build_liverpool_url(page=page),
                        self.known_seller_urls[page],
                    )

    def test_playstation_landing_page_builds_seller_filtered_url(self) -> None:
        encrypted_url = "N-playstationToken%3D"
        with self._mock_seller_url(encrypted_url, LiverpoolPage.playstation) as resolver:
            self.assertEqual(
                build_liverpool_url(page=LiverpoolPage.playstation),
                "https://www.liverpool.com.mx/tienda/cat1161024/N-playstationToken%3D?showPLP",
            )
            self.assertEqual(
                build_liverpool_url(page=LiverpoolPage.playstation, query="dualsense"),
                "https://www.liverpool.com.mx/tienda/N-playstationToken%3D?s=dualsense",
            )

        body = resolver.call_args.kwargs["json"]
        self.assertEqual(body["categoryId"], "cat1161024")
        self.assertEqual(body["appliedFilters"], [LIVERPOOL_SELLER_FILTER_ID])

    def test_zapatos_talla_seeded_urls_match_documented_fixtures(self) -> None:
        self.assertEqual(
            build_zapatos_talla_url("26.5 cm"),
            "https://www.liverpool.com.mx/tienda/zapatos/"
            "N-DSNCDwNe0TQmqDl9oaVW3NMMVWOMWKnBTxTMkuCm8FJSYNNgpfpKZJhbO%2FeHb1VtGHTmN%2F9HShTHsphfUIoyiA%3D%3D",
        )
        self.assertEqual(
            build_zapatos_talla_url("27 cm"),
            "https://www.liverpool.com.mx/tienda/zapatos/"
            "N-DSNCDwNe0TQmqDl9oaVW3P49z6zKiRdLU4IIpgT97FoXJTIUSUZJlJZf8BVMSBuD0Bn3ELEZFYONaFEjhb%2FKag%3D%3D",
        )
        self.assertEqual(
            build_zapatos_talla_url(["26.5", "27 cm"]),
            "https://www.liverpool.com.mx/tienda/zapatos/"
            "N-DSNCDwNe0TQmqDl9oaVW3NMMVWOMWKnBTxTMkuCm8FK8nbspJJHyymB2JB2cQAhiuNp2DrMWVxMOlgTqk%2BZcRA%3D%3D",
        )

    def test_zapatos_talla_seller_fixtures_are_generated(self) -> None:
        self.assertEqual(
            build_liverpool_url(page=LiverpoolPage.zapatos_hombre, talla="26.5 cm"),
            "https://www.liverpool.com.mx/tienda/zapatos/"
            "N-S1sLjNksKoG%2BC2c1SDPsHO5452djswD00Q%2BK5TJ2fOqRWmHi9IHo7DohJbsKzc6imfhD61Tn4E65LWhl6f0t7AaY0oFPrT%2BCxbnEWoFgLLk%3D",
        )
        self.assertEqual(
            build_liverpool_url(page=LiverpoolPage.zapatos_hombre, talla=["27"]),
            "https://www.liverpool.com.mx/tienda/zapatos/"
            "N-S1sLjNksKoG%2BC2c1SDPsHO5452djswD00Q%2BK5TJ2fOozVqOODGOtunTN8e%2BvWv35ro9Gu4Wj4ohV%2F0lAwq%2BnstUtcATsuqxRHlNDb77mhq0%3D",
        )
        self.assertEqual(
            build_liverpool_url(page=LiverpoolPage.zapatos_hombre, talla=["27 cm", "26.5 cm"]),
            "https://www.liverpool.com.mx/tienda/zapatos/"
            "N-S1sLjNksKoG%2BC2c1SDPsHO5452djswD00Q%2BK5TJ2fOqRWmHi9IHo7DohJbsKzc6ie3dJdH0yzQY5Wf7pWwAqdcmJw7uqeFRVZhuwaUGwFJM%3D",
        )
        self.assertNotEqual(
            build_liverpool_url(page=LiverpoolPage.zapatos_hombre, talla="26.5 cm"),
            build_zapatos_talla_url("26.5 cm"),
        )

    def test_zapatos_talla_routes_fail_fast_for_unsupported_combinations(self) -> None:
        with self.assertRaisesRegex(ValueError, "talla filters require a page"):
            build_liverpool_url(talla="26.5 cm")
        with self.assertRaisesRegex(ValueError, "only for 'zapatos_hombre'"):
            build_liverpool_url(page=LiverpoolPage.playstation, talla="26.5 cm")
        with self.assertRaisesRegex(ValueError, "do not support query combinations"):
            build_liverpool_url(page=LiverpoolPage.zapatos_hombre, talla="26.5 cm", query="nike")
        with self.assertRaisesRegex(ValueError, "Unsupported Liverpool talla"):
            build_liverpool_url(page=LiverpoolPage.zapatos_hombre, talla="30 cm")

    def test_resolver_rejects_missing_token(self) -> None:
        payload = self._seller_payload("", LiverpoolPage.nintendo)
        with patch(
            "provider.liverpool.urls.requests.post",
            return_value=self._MockResponse(payload),
        ):
            with self.assertRaisesRegex(ValueError, "no encrypted URL"):
                build_page_url(LiverpoolPage.nintendo)

    def test_resolver_rejects_missing_seller_refinement(self) -> None:
        payload = {
            "data": {
                "encryptedFilters": self._segment_for_page(LiverpoolPage.nintendo),
                "filter": 'attributes.ancestors: ANY("CAT5030010")',
                "filtersGroups": [],
            }
        }
        with patch(
            "provider.liverpool.urls.requests.post",
            return_value=self._MockResponse(payload),
        ):
            with self.assertRaisesRegex(ValueError, "did not select Liverpool as seller"):
                build_page_url(LiverpoolPage.nintendo)

    def test_resolver_rejects_wrong_page_ancestor(self) -> None:
        payload = {
            "data": {
                "encryptedFilters": self._segment_for_page(LiverpoolPage.nintendo),
                "filter": 'attributes.sellernames: ANY("liverpool") AND attributes.ancestors: ANY("CATWRONG")',
                "filtersGroups": [],
            }
        }
        with patch(
            "provider.liverpool.urls.requests.post",
            return_value=self._MockResponse(payload),
        ):
            with self.assertRaisesRegex(ValueError, "did not select page ancestor"):
                build_page_url(LiverpoolPage.nintendo)

    def test_resolver_request_failure_requires_explicit_url(self) -> None:
        with patch(
            "provider.liverpool.urls.requests.post",
            side_effect=lv_urls.requests.RequestException("boom"),
        ):
            with self.assertRaisesRegex(ValueError, "request failed"):
                build_page_url(LiverpoolPage.nintendo)

    def test_liverpool_page_hierarchy_is_strict(self) -> None:
        self.assertEqual(
            resolve_page_path("Home", "Videojuegos", "Nintendo", "Juegos Nintendo"),
            LiverpoolPage.juegos_nintendo,
        )
        self.assertEqual(
            resolve_page_path("Home", "Videojuegos", "PlayStation"),
            LiverpoolPage.playstation,
        )
        self.assertEqual(
            resolve_page_path("Home", "Hombre", "Zapatos"),
            LiverpoolPage.zapatos_hombre,
        )
        self.assertEqual(
            resolve_page_path("Línea Blanca y Electrodomésticos", "Electrodomésticos de Cocina"),
            LiverpoolPage.electrodomesticos_de_cocina,
        )
        with self.assertRaisesRegex(ValueError, "Unknown Liverpool page path"):
            resolve_page_path(
                "Home",
                "Línea Blanca y Electrodomésticos",
                "Electrodomésticos de Cocina",
                "Juegos Nintendo",
            )

    def test_prompt_aliases_resolve_to_canonical_pages(self) -> None:
        self.assertEqual(resolve_page("Hornos eléctricos"), LiverpoolPage.hornos_electricos)
        self.assertEqual(resolve_page("Consolas y videojuegos Nintendo"), LiverpoolPage.nintendo)
        self.assertEqual(resolve_page("PlayStation"), LiverpoolPage.playstation)
        self.assertEqual(resolve_page("Zapatos"), LiverpoolPage.zapatos_hombre)

    def test_preview_liverpool_url_accepts_plain_strings(self) -> None:
        with self._mock_seller_url("N-8BAqotJ%2FHmg946pY%2BECjww%3D%3D?s=ventilador"):
            self.assertEqual(
                preview_liverpool_url(query="ventilador"),
                "https://www.liverpool.com.mx/tienda/"
                "N-8BAqotJ%2FHmg946pY%2BECjww%3D%3D?s=ventilador",
            )
        with self._mock_seller_url("N-8BAqotJ%2FHmg946pY%2BECjww%3D%3D?s=macbook"):
            self.assertEqual(
                preview_liverpool_url(query="macbook"),
                "https://www.liverpool.com.mx/tienda/"
                "N-8BAqotJ%2FHmg946pY%2BECjww%3D%3D?s=macbook",
            )
        with self._mock_seller_url(
            self._segment_for_page(LiverpoolPage.hornos_electricos),
            LiverpoolPage.hornos_electricos,
        ):
            self.assertEqual(
                preview_liverpool_url(page="Hornos eléctricos"),
                self.known_seller_urls[LiverpoolPage.hornos_electricos],
            )
        with self._mock_seller_url(
            self._segment_for_page(LiverpoolPage.hornos_electricos),
            LiverpoolPage.hornos_electricos,
        ):
            self.assertEqual(
                preview_liverpool_url(page="Hornos eléctricos", query="black"),
                "https://www.liverpool.com.mx/tienda/"
                "N-S1sLjNksKoG%2BC2c1SDPsHDLkL1UcSQDvtOqhAagDbUKyQ4wGi88mGsyxG1aD%2B3uQ?s=black",
            )
        with self._mock_seller_url(
            self._segment_for_page(LiverpoolPage.computacion),
            LiverpoolPage.computacion,
        ):
            self.assertEqual(
                preview_liverpool_url(page="Computación", show_plp=True),
                self.known_seller_urls[LiverpoolPage.computacion],
            )

    def test_preview_liverpool_url_returns_explicit_url_unchanged(self) -> None:
        self.assertEqual(
            preview_liverpool_url(
                url="https://example.test/custom",
                query="ignored",
                page="Hornos eléctricos",
                brand="custom",
            ),
            "https://example.test/custom",
        )

    def test_preview_liverpool_url_reports_unknown_string_options(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unknown Liverpool page"):
            preview_liverpool_url(page="missing")

    def test_canonical_page_url_is_documentation_only(self) -> None:
        self.assertEqual(
            build_canonical_page_url(LiverpoolPage.nintendo, show_plp=True),
            "https://www.liverpool.com.mx/tienda/nintendo/cat5030010?showPLP",
        )

    def test_pagination_segment_is_added_before_query(self) -> None:
        self.assertEqual(
            append_page_segment("https://www.liverpool.com.mx/tienda/N-token?s=ventilador", 2),
            "https://www.liverpool.com.mx/tienda/N-token/page-2?s=ventilador",
        )
        self.assertEqual(
            append_page_segment(
                "https://www.liverpool.com.mx/tienda/N-token/page-2?s=ventilador",
                3,
            ),
            "https://www.liverpool.com.mx/tienda/N-token/page-3?s=ventilador",
        )
        self.assertEqual(
            current_page_number("https://www.liverpool.com.mx/tienda/N-token/page-2?s=iphone"),
            2,
        )


class PalacioUrlTests(unittest.TestCase):
    def test_search_url_hyphenates_global_query(self) -> None:
        self.assertEqual(
            build_palacio_search_url("pokemon legends arceus"),
            "https://www.elpalaciodehierro.com/buscar?q=pokemon-legends-arceus",
        )
        self.assertEqual(
            build_palacio_url(query="magic keyboard"),
            "https://www.elpalaciodehierro.com/buscar?q=magic-keyboard",
        )

    def test_global_palacio_search_requires_explicit_query(self) -> None:
        with self.assertRaisesRegex(ValueError, "search query cannot be blank"):
            build_palacio_url()

    def test_page_urls_use_documented_palacio_route_segments(self) -> None:
        self.assertEqual(
            build_palacio_page_url(PalacioPage.electronica),
            "https://www.elpalaciodehierro.com/electronica/",
        )
        self.assertEqual(
            build_palacio_page_url(PalacioPage.laptops),
            "https://www.elpalaciodehierro.com/electronica/computadoras/laptops/",
        )

    def test_page_brand_filters_are_sorted_encoded_and_deduplicated(self) -> None:
        self.assertEqual(
            build_palacio_page_url(
                PalacioPage.computo,
                brands=["asus", "Apple", "apple"],
            ),
            "https://www.elpalaciodehierro.com/electronica/computadoras/apple%7Casus/",
        )
        self.assertEqual(
            build_palacio_page_url(PalacioPage.computo, brands="dell"),
            "https://www.elpalaciodehierro.com/electronica/computadoras/dell/",
        )
        self.assertEqual(
            build_palacio_url(
                page=PalacioPage.computo,
                brands=(brand for brand in ("razer", "alienware", "dell")),
            ),
            "https://www.elpalaciodehierro.com/electronica/computadoras/"
            "alienware%7Cdell%7Crazer/",
        )

    def test_page_aliases_resolve_to_palacio_routes(self) -> None:
        self.assertEqual(resolve_palacio_page("Cómputo"), PalacioPage.computo)
        self.assertEqual(resolve_palacio_page("hogar/linea-blanca"), PalacioPage.linea_blanca)

    def test_preview_explicit_url_wins_over_structured_fields(self) -> None:
        self.assertEqual(
            preview_palacio_url(
                url="https://example.test/custom",
                page="Computo",
                brands=["apple"],
            ),
            "https://example.test/custom",
        )

    def test_unsupported_structured_combinations_fail_fast(self) -> None:
        with self.assertRaisesRegex(ValueError, "page URLs do not support global query"):
            build_palacio_url(query="apple", page=PalacioPage.laptops)
        with self.assertRaisesRegex(ValueError, "brand filters require a page"):
            build_palacio_url(query="apple", brands=["apple"])
        with self.assertRaisesRegex(ValueError, "Unknown Palacio page"):
            build_palacio_page_url("missing")


class ProviderParserEdgeTests(unittest.TestCase):
    def test_amazon_parser_skips_results_without_price_or_asin(self) -> None:
        html = """
        <div data-component-type="s-search-result" data-asin="">
          <h2><span>No ASIN</span></h2>
          <span class="a-price"><span class="a-offscreen">$10.00</span></span>
        </div>
        <div data-component-type="s-search-result" data-asin="B012345678">
          <h2><span>No price</span></h2>
        </div>
        """
        with empty_article_storage():
            motor = Amazon(
                "macbook",
                build_amazon_url(query="macbook"),
                storage_path="tests/amazon-edge.json",
            )

        items, next_url = motor.scrape_page({"content": html, "url": motor.url})

        self.assertEqual(items, [])
        self.assertIsNone(next_url)

    def test_liverpool_marks_incomplete_when_next_data_is_missing(self) -> None:
        with empty_article_storage():
            motor = Liverpool(
                "Laptops", "https://example.test/lv", storage_path="tests/lv-edge.json"
            )

        items, next_url = motor.scrape_page({"content": "<html></html>", "url": motor.url})

        self.assertEqual(items, [])
        self.assertIsNone(next_url)
        self.assertTrue(motor._scrape_incomplete)

    def test_liverpool_skips_malformed_records_but_keeps_valid_records(self) -> None:
        page_object = {
            "query": {
                "data": {
                    "mainContent": {
                        "records": [
                            {"allMeta": {"id": "ok", "title": "Laptop", "minimumPromoPrice": 10.0}},
                            {"allMeta": {"id": "bad"}},
                        ],
                        "pageInfo": {"noOfPages": "1"},
                    }
                }
            }
        }
        html = f"<script id='__NEXT_DATA__'>{json.dumps(page_object)}</script>"
        with empty_article_storage():
            motor = Liverpool(
                "Laptops", "https://example.test/lv", storage_path="tests/lv-records.json"
            )

        items, _ = motor.scrape_page({"content": html, "url": motor.url})

        self.assertEqual([item["identifier"] for item in items], ["ok"])

    def test_liverpool_pagination_preserves_search_query(self) -> None:
        page_object = {
            "query": {
                "data": {
                    "mainContent": {
                        "records": [],
                        "pageInfo": {"noOfPages": "2"},
                    }
                }
            }
        }
        html = f"<script id='__NEXT_DATA__'>{json.dumps(page_object)}</script>"
        with empty_article_storage():
            motor = Liverpool(
                "Ventilador",
                "https://www.liverpool.com.mx/tienda/N-token?s=ventilador",
                storage_path="tests/lv-pagination.json",
            )

        _, next_url = motor.scrape_page({"content": html, "url": motor.url})

        self.assertEqual(
            next_url,
            "https://www.liverpool.com.mx/tienda/N-token/page-2?s=ventilador",
        )

    def test_liverpool_parses_next_app_router_rsc_initial_results(self) -> None:
        initial_results = {
            "records": [
                {
                    "productId": "1196338436",
                    "title": "Laptop Macbook Neo 13 pulgadas",
                    "priceInfo": {
                        "salePrice": 15999,
                        "listPrice": {"minPrice": 15999, "maxPrice": 18499},
                        "promoPrice": {"minPrice": 15999, "maxPrice": 18499},
                    },
                },
                {
                    "productId": "1206318232",
                    "title": "Juego EA Sports FC 27",
                    "priceInfo": {
                        "salePrice": 1599,
                        "listPrice": {"price": 1599},
                        "promoPrice": {"price": 1499.5},
                    },
                },
                {
                    "productId": "bad-no-price",
                    "title": "Sin Precio",
                    "priceInfo": {},
                },
            ],
            "pageInfo": {"noOfPages": 3, "currentPage": 1},
        }
        rsc_chunk = (
            '389:[["$","$L3af",null,{"events":"$undefined","initialResults":'
            + json.dumps(initial_results)
            + "}]]"
        )
        html = f"<html><body><script>self.__next_f.push([1,{json.dumps(rsc_chunk)}])</script></body></html>"
        with empty_article_storage():
            motor = Liverpool(
                "Apple",
                "https://www.liverpool.com.mx/tienda/catst2145072/N-token?showPLP",
                storage_path="tests/lv-rsc.json",
            )

        items, next_url = motor.scrape_page({"content": html, "url": motor.url})

        self.assertFalse(motor._scrape_incomplete)
        self.assertEqual(
            items,
            [
                {
                    "identifier": "1196338436",
                    "title": "Laptop Macbook Neo 13 pulgadas",
                    "price": 15999.0,
                    "url": "https://www.liverpool.com.mx/tienda/pdp/laptop-macbook-neo-13-pulgadas/1196338436",
                },
                {
                    "identifier": "1206318232",
                    "title": "Juego EA Sports FC 27",
                    "price": 1499.5,
                    "url": "https://www.liverpool.com.mx/tienda/pdp/juego-ea-sports-fc-27/1206318232",
                },
            ],
        )
        self.assertEqual(
            next_url,
            "https://www.liverpool.com.mx/tienda/catst2145072/N-token/page-2?showPLP",
        )

    def test_palacio_next_url_advances_start_until_total_is_reached(self) -> None:
        with empty_article_storage():
            motor = PalacioDeHierro(
                "Macbook",
                "https://www.elpalaciodehierro.com/buscar?q=macbook",
                storage_path="tests/ph-edge.json",
            )

        self.assertEqual(
            motor._next_url(
                "https://www.elpalaciodehierro.com/buscar?q=macbook&start=52",
                items_on_page=52,
                total=120,
                page_size=52,
            ),
            "https://www.elpalaciodehierro.com/buscar?q=macbook&start=104",
        )
        self.assertIsNone(
            motor._next_url(
                "https://www.elpalaciodehierro.com/buscar?q=macbook&start=104",
                items_on_page=16,
                total=120,
                page_size=52,
            )
        )

    def test_palacio_page_size_falls_back_when_options_are_invalid(self) -> None:
        soup = BeautifulSoup(
            '<section data-component="search/ConstructorSearch" data-component-options="{bad"></section>',
            "html.parser",
        )
        with empty_article_storage():
            motor = PalacioDeHierro(
                "Macbook", "https://example.test/ph", storage_path="tests/ph-size.json"
            )

        self.assertEqual(motor._page_size(soup), 52)
