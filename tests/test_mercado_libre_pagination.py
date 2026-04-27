from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from provider.mercado_libre.motor import MercadoLibre
from provider.mercado_libre.utils import Category


def _make_html(*, count: int, total_label: str, limit: int = 51) -> str:
    items = []
    for i in range(count):
        items.append(
            f"""
            <li class="ui-search-layout__item">
              <a class="poly-component__title" href="https://www.mercadolibre.com.mx/item-{i}">Item {i}</a>
              <span class="andes-money-amount__fraction">123</span>
            </li>
            """
        )

    return f"""
    <html>
      <head>
        <script id="__NEXT_DATA__" type="application/json">
          {{"props":{{"pageProps":{{"initialState":{{"melidata_track":{{"event_data":{{"limit":{limit}}}}}}}}}}}}}
        </script>
      </head>
      <body>
        <section class="ui-search-results">
          <div>{total_label}</div>
          <ol class="ui-search-layout">
            {''.join(items)}
          </ol>
          <ul class="andes-pagination">
            <li class="andes-pagination__button--next">
              <a title="Siguiente" data-andes-pagination-control="next" href="/next">Siguiente</a>
            </li>
          </ul>
        </section>
      </body>
    </html>
    """


class MercadoLibrePaginationTests(unittest.TestCase):
    def test_does_not_generate_next_url_when_total_results_are_exhausted(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            motor = MercadoLibre("atlas", Category.deportes_jersey, storage_path=str(Path(tmpdir) / "storage.json"))
            html = _make_html(count=51, total_label="623 resultados")

            items, next_url = motor.scrape_page({"content": html, "url": "https://listado.mercadolibre.com.mx/deportes-fitness/futbol/atlas_Desde_572_NoIndex_True"})

            self.assertEqual(len(items), 51)
            self.assertIsNone(next_url)

    def test_generates_next_url_when_more_results_remain(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            motor = MercadoLibre("atlas", Category.deportes_jersey, storage_path=str(Path(tmpdir) / "storage.json"))
            html = _make_html(count=51, total_label="700 resultados")

            items, next_url = motor.scrape_page({"content": html, "url": "https://listado.mercadolibre.com.mx/deportes-fitness/futbol/atlas_Desde_572_NoIndex_True"})

            self.assertEqual(len(items), 51)
            self.assertIsNotNone(next_url)
            self.assertIn("_Desde_623_", next_url)

    def test_falls_back_to_short_page_heuristic_without_total_results(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            motor = MercadoLibre("atlas", Category.deportes_jersey, storage_path=str(Path(tmpdir) / "storage.json"))
            html = _make_html(count=12, total_label="Sin etiqueta")

            items, next_url = motor.scrape_page({"content": html, "url": "https://listado.mercadolibre.com.mx/deportes-fitness/futbol/atlas_Desde_572_NoIndex_True"})

            self.assertEqual(len(items), 12)
            self.assertIsNone(next_url)


if __name__ == "__main__":
    unittest.main()
