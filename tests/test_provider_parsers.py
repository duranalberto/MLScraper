from __future__ import annotations

import json
import unittest

from bs4 import BeautifulSoup

from provider.amazon.motor import Amazon
from provider.amazon.options import Seller
from provider.liverpool.motor import Liverpool
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
