from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scraper.runtime.url_preview import preview_job_url


class UrlPreviewTests(unittest.TestCase):
    def _write_jobs(self, content: str) -> Path:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        path = Path(tmpdir.name) / "jobs.yaml"
        path.write_text(content, encoding="utf-8")
        return path

    def test_preview_liverpool_job_generates_url_on_demand(self) -> None:
        path = self._write_jobs("""
jobs:
  - provider: lv
    job_id: PlayStation
    category: playstation
""")
        with patch(
            "provider.liverpool.urls.requests.get",
            return_value=_MockResponse(
                {
                    "mainContent": {
                        "originalRequest": {"encryptedFullUrl": "N-playstationToken"},
                        "selectedNavigation": [
                            {"name": "ancestors", "refinements": [{"value": "CAT1161024"}]},
                            {
                                "name": "variants.sellernames",
                                "refinements": [{"value": "liverpool"}],
                            },
                        ],
                    }
                }
            ),
        ):
            self.assertEqual(
                preview_job_url("PlayStation", provider="lv", config_path=path),
                "https://www.liverpool.com.mx/tienda/playstation/N-playstationToken",
            )

    def test_preview_job_requires_existing_match(self) -> None:
        path = self._write_jobs("""
jobs:
  - provider: lv
    job_id: Other
    category: playstation
""")
        with self.assertRaisesRegex(ValueError, "No job found"):
            preview_job_url("PlayStation", provider="lv", config_path=path)

    def test_preview_liverpool_job_supports_seeded_talla(self) -> None:
        path = self._write_jobs("""
jobs:
  - provider: lv
    job_id: Zapatos 26.5 y 27
    category: zapatos_hombre
    talla:
      - "26.5"
      - "27 cm"
""")
        self.assertEqual(
            preview_job_url("Zapatos 26.5 y 27", provider="lv", config_path=path),
            "https://www.liverpool.com.mx/tienda/zapatos/"
            "N-S1sLjNksKoG%2BC2c1SDPsHO5452djswD00Q%2BK5TJ2fOqRWmHi9IHo7DohJbsKzc6ie3dJdH0yzQY5Wf7pWwAqdcmJw7uqeFRVZhuwaUGwFJM%3D",
        )


class _MockResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self.payload
