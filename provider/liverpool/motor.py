import json
import re
from bs4 import BeautifulSoup
from traceback import format_exc
from scraper.motor import Motor


class Liverpool(Motor):
    def __init__(self, search_term: str, url: str, *, storage_path: str):
        super().__init__(search_term, url, storage_path=storage_path)

    def scrape_page(self, body: dict):
        items = []
        next_url = None

        soup = BeautifulSoup(body['content'], 'html.parser')
        root = soup.find('script', id='__NEXT_DATA__')
        page_object = json.loads(root.string)
        records = page_object['query']['data']['mainContent']['records']

        for record in records:
            item = record['allMeta']
            formatted_title = item['title'].lower().replace(" ", "-")
            identifier = item['id']
            items.append({
                'identifier': identifier,
                'title': item['title'],
                'price': item['minimumPromoPrice'],
                'url': f'https://www.liverpool.com.mx/tienda/pdp/{formatted_title}/{identifier}',
            })

        try:
            noOfPages = int(page_object['query']['data']['mainContent']['pageInfo']['noOfPages'])
            pattern = r"/page-(\d+)$"
            matches = re.findall(pattern, body['url'])
            currentPage = int(matches[-1]) if matches else 1
            next_page = currentPage + 1
            if currentPage < noOfPages:
                next_url = f'{self.url}/page-{next_page}'
        except Exception:
            print(format_exc())

        return items, next_url