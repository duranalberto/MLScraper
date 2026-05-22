import json
import logging
from bs4 import BeautifulSoup
from shared.scraping.motor import Motor

from .urls import append_page_segment, current_page_number

logger = logging.getLogger(__name__)


class Liverpool(Motor):
    PROVIDER_KEY = "lv"

    def __init__(self, job_id: str, url: str, *, storage_path: str):
        super().__init__(job_id, url, storage_path=storage_path)

    def scrape_page(self, body: dict):
        items = []
        next_url = None

        soup = BeautifulSoup(body["content"], "html.parser")
        root = soup.find("script", id="__NEXT_DATA__")

        if not root or not root.string:
            self._scrape_incomplete = True
            logger.error(
                "[Liverpool] __NEXT_DATA__ script tag missing or empty for '%s'. "
                "Liverpool may have changed their page structure.",
                self.job_id,
            )
            return [], None

        try:
            page_object = json.loads(root.string)
            records = page_object["query"]["data"]["mainContent"]["records"]
        except json.JSONDecodeError as e:
            self._scrape_incomplete = True
            logger.error(
                "[Liverpool] Failed to parse __NEXT_DATA__ JSON for '%s': %s", self.job_id, e
            )
            return [], None
        except (KeyError, TypeError) as e:
            self._scrape_incomplete = True
            logger.error(
                "[Liverpool] Unexpected JSON structure for '%s' — key %s not found. "
                "Liverpool may have changed their data schema.",
                self.job_id,
                e,
            )
            return [], None

        for record in records:
            try:
                item = record["allMeta"]
                formatted_title = item["title"].lower().replace(" ", "-")
                identifier = item["id"]
                items.append(
                    {
                        "identifier": identifier,
                        "title": item["title"],
                        "price": item["minimumPromoPrice"],
                        "url": f"https://www.liverpool.com.mx/tienda/pdp/{formatted_title}/{identifier}",
                    }
                )
            except (KeyError, TypeError) as e:
                logger.warning("[Liverpool] Skipping malformed record for '%s': %s", self.job_id, e)
                continue

        try:
            noOfPages = int(page_object["query"]["data"]["mainContent"]["pageInfo"]["noOfPages"])
            currentPage = current_page_number(body["url"])
            next_page = currentPage + 1
            if currentPage < noOfPages:
                next_url = append_page_segment(body["url"], next_page)
        except KeyError, TypeError, ValueError:
            pass

        return items, next_url
