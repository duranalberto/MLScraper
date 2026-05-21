from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from bs4 import BeautifulSoup

from provider.amazon.motor import Amazon
from provider.amazon.options import Seller
from provider.liverpool import urls as lv_urls
from provider.liverpool.motor import Liverpool
from provider.liverpool.options import (
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
    current_page_number,
    preview_liverpool_url,
)
from provider.mercado_libre import parser as ml_parser
from provider.mercado_libre.options import Category
from provider.mercado_libre.urls import construct_search_url, get_identifier
from provider.palacio_de_hierro.motor import PalacioDeHierro
from tests.helpers import empty_article_storage


class MercadoLibreUrlTests(unittest.TestCase):
    def test_get_identifier_prefers_wid_then_product_ids(self) -> None:
        self.assertEqual(get_identifier("https://example.test/item?wid=MLM123"), "MLM123")
        self.assertEqual(get_identifier("https://example.test/up/MLMU123"), "MLMU123")
        self.assertEqual(get_identifier("https://example.test/p/MLM999"), "MLM999")

    def test_construct_search_url_handles_category_variants(self) -> None:
        self.assertEqual(
            construct_search_url("Nintendo DS", Category.none),
            "https://listado.mercadolibre.com.mx/nintendo-ds_NoIndex_True",
        )
        self.assertIn(
            "_CustId_527927603", construct_search_url("MacBook Pro", Category.apple_official)
        )


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
            "https://www.liverpool.com.mx/tienda/l%C3%ADnea-blanca-y-electrodom%C3%A9sticos/"
            "N-S1sLjNksKoG%2BC2c1SDPsHKIBKNV9C39qzAQKlWKyNPun2aJSsdu2MIlSvIBK7fjU"
        ),
        LiverpoolPage.electrodomesticos_de_cocina: (
            "https://www.liverpool.com.mx/tienda/electrodom%C3%A9sticos-de-cocina/"
            "N-S1sLjNksKoG%2BC2c1SDPsHE2WJgzT1N18wn6bm3Crd%2BLSeXXyPBbJePl81tX2VT0v"
        ),
        LiverpoolPage.hornos_electricos: (
            "https://www.liverpool.com.mx/tienda/hornos-el%C3%A9ctricos/"
            "N-S1sLjNksKoG%2BC2c1SDPsHDLkL1UcSQDvtOqhAagDbUKyQ4wGi88mGsyxG1aD%2B3uQ"
        ),
        LiverpoolPage.computacion: (
            "https://www.liverpool.com.mx/tienda/computaci%C3%B3n/"
            "N-S1sLjNksKoG%2BC2c1SDPsHN%2BJ%2BVnTTvZIur1XfBh58ds%3D"
        ),
        LiverpoolPage.laptops: (
            "https://www.liverpool.com.mx/tienda/laptops/"
            "N-S1sLjNksKoG%2BC2c1SDPsHADb51HPoq41uykVTx%2F8p7q4Lv5kmJ%2FB7n9SHDZAiZOr"
        ),
        LiverpoolPage.videojuegos: (
            "https://www.liverpool.com.mx/tienda/videojuegos/"
            "N-S1sLjNksKoG%2BC2c1SDPsHHgKKoxCWs4ssLitZ2y5bdQ%3D"
        ),
        LiverpoolPage.nintendo: (
            "https://www.liverpool.com.mx/tienda/nintendo/"
            "N-S1sLjNksKoG%2BC2c1SDPsHKoOUK876ftr4S1vpt6rlqU%3D"
        ),
        LiverpoolPage.juegos_nintendo: (
            "https://www.liverpool.com.mx/tienda/juegos-nintendo/"
            "N-S1sLjNksKoG%2BC2c1SDPsHEMtiDHLusAuxLK0y30fWRU5PhnhiYjJElHuz9EseRgf"
        ),
        LiverpoolPage.apple: (
            "https://www.liverpool.com.mx/tienda/apple/"
            "N-S1sLjNksKoG%2BC2c1SDPsHNm0puD%2BxMdUs8fFWfZr2VPe%2F6v1sCWzDBDSulA990d4"
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
        selected_navigation = []
        if page is not None:
            selected_navigation.append(
                {
                    "name": "ancestors",
                    "refinements": [{"value": page.value.category_id}],
                }
            )
        selected_navigation.append(
            {
                "name": LIVERPOOL_SELLER_REFINEMENT_NAME,
                "refinements": [{"value": LIVERPOOL_SELLER_REFINEMENT_VALUE}],
            }
        )
        return {
            "mainContent": {
                "originalRequest": {"encryptedFullUrl": encrypted_url},
                "selectedNavigation": selected_navigation,
            }
        }

    def _mock_seller_url(self, encrypted_url: str, page: LiverpoolPage | None = None):
        return patch(
            "provider.liverpool.urls.requests.get",
            return_value=self._MockResponse(self._seller_payload(encrypted_url, page)),
        )

    def _segment_for_page(self, page: LiverpoolPage) -> str:
        return self.known_seller_urls[page].rsplit("/", 1)[-1]

    def test_generated_search_url_uses_verified_liverpool_seller_resolver(self) -> None:
        encrypted_url = "N-8BAqotJ%2FHmg946pY%2BECjww%3D%3D?s=ventilador"
        with self._mock_seller_url(encrypted_url) as resolver:
            self.assertEqual(
                build_liverpool_url("Ventilador Liverpool", query="ventilador"),
                "https://www.liverpool.com.mx/tienda/"
                "N-8BAqotJ%2FHmg946pY%2BECjww%3D%3D?s=ventilador",
            )

        params = resolver.call_args.kwargs["params"]
        self.assertEqual(params["s"], "ventilador")
        self.assertEqual(params["Fs"], "liverpool")

    def test_search_term_falls_back_to_verified_liverpool_seller_search(self) -> None:
        encrypted_url = "N-8BAqotJ%2FHmg946pY%2BECjww%3D%3D?s=macbook"
        with self._mock_seller_url(encrypted_url):
            self.assertEqual(
                build_liverpool_url("macbook"),
                "https://www.liverpool.com.mx/tienda/"
                "N-8BAqotJ%2FHmg946pY%2BECjww%3D%3D?s=macbook",
            )

    def test_generated_brand_filter_requires_explicit_url(self) -> None:
        with self.assertRaisesRegex(ValueError, "brand filters require an explicit url"):
            build_liverpool_url("Refrigeradores LG", brand="lg")

    def test_generated_page_url_uses_resolved_seller_segment(self) -> None:
        with self._mock_seller_url(
            self._segment_for_page(LiverpoolPage.hornos_electricos),
            LiverpoolPage.hornos_electricos,
        ) as resolver:
            self.assertEqual(
                build_liverpool_url(
                    "Hornos eléctricos",
                    page=LiverpoolPage.hornos_electricos,
                ),
                self.known_seller_urls[LiverpoolPage.hornos_electricos],
            )

        params = resolver.call_args.kwargs["params"]
        self.assertEqual(params["categoryId"], "CATST53843927")
        self.assertNotIn("s", params)

    def test_generated_page_query_uses_root_token_form(self) -> None:
        with self._mock_seller_url(
            self._segment_for_page(LiverpoolPage.hornos_electricos),
            LiverpoolPage.hornos_electricos,
        ):
            self.assertEqual(
                build_liverpool_url(
                    "Hornos Black", page=LiverpoolPage.hornos_electricos, query="black"
                ),
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
                        build_liverpool_url(page.value.display_name, page=page),
                        self.known_seller_urls[page],
                    )

    def test_resolver_rejects_missing_token(self) -> None:
        payload = self._seller_payload("", LiverpoolPage.nintendo)
        with patch(
            "provider.liverpool.urls.requests.get",
            return_value=self._MockResponse(payload),
        ):
            with self.assertRaisesRegex(ValueError, "no encrypted URL"):
                build_page_url(LiverpoolPage.nintendo)

    def test_resolver_rejects_missing_seller_refinement(self) -> None:
        payload = self._seller_payload(self._segment_for_page(LiverpoolPage.nintendo))
        payload["mainContent"]["selectedNavigation"] = [
            {"name": "ancestors", "refinements": [{"value": "CAT5030010"}]}
        ]
        with patch(
            "provider.liverpool.urls.requests.get",
            return_value=self._MockResponse(payload),
        ):
            with self.assertRaisesRegex(ValueError, "did not select Liverpool as seller"):
                build_page_url(LiverpoolPage.nintendo)

    def test_resolver_rejects_wrong_page_ancestor(self) -> None:
        payload = self._seller_payload(self._segment_for_page(LiverpoolPage.nintendo))
        payload["mainContent"]["selectedNavigation"] = [
            {"name": "ancestors", "refinements": [{"value": "CATWRONG"}]},
            {
                "name": LIVERPOOL_SELLER_REFINEMENT_NAME,
                "refinements": [{"value": LIVERPOOL_SELLER_REFINEMENT_VALUE}],
            },
        ]
        with patch(
            "provider.liverpool.urls.requests.get",
            return_value=self._MockResponse(payload),
        ):
            with self.assertRaisesRegex(ValueError, "did not select page ancestor"):
                build_page_url(LiverpoolPage.nintendo)

    def test_resolver_request_failure_requires_explicit_url(self) -> None:
        with patch(
            "provider.liverpool.urls.requests.get",
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

    def test_preview_liverpool_url_accepts_plain_strings(self) -> None:
        with self._mock_seller_url("N-8BAqotJ%2FHmg946pY%2BECjww%3D%3D?s=ventilador"):
            self.assertEqual(
                preview_liverpool_url(query="ventilador"),
                "https://www.liverpool.com.mx/tienda/"
                "N-8BAqotJ%2FHmg946pY%2BECjww%3D%3D?s=ventilador",
            )
        with self._mock_seller_url("N-8BAqotJ%2FHmg946pY%2BECjww%3D%3D?s=macbook"):
            self.assertEqual(
                preview_liverpool_url(search_term="macbook"),
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
            motor = Amazon("macbook", Seller.none, storage_path="tests/amazon-edge.json")

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
