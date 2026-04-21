import re
import json
from bs4 import BeautifulSoup
from scraper.motor import Motor
from .utils import Category, get_identifier, construct_search_url


class MercadoLibre(Motor):

    def __init__(
        self,
        search_term: str,
        category: Category = Category.consolas_videojuegos,
        *,
        storage_path: str,
    ):
        super().__init__(search_term, construct_search_url(search_term, category), storage_path=storage_path)

    def scrape_page(self, body):
        items = []
        next_url = None

        html = body.get('content', '')
        soup = BeautifulSoup(html, 'html.parser')

        root = soup.find('section', class_='ui-search-results')
        if not root:
            return items, None

        for item in root.select('ol.ui-search-layout > li.ui-search-layout__item'):
            try:
                link_tag = item.select_one(
                    'a.poly-component__title[href], '
                    'a.ui-search-item__group__element[href], '
                    'a.ui-search-link[href], '
                    'h2 a[href], '
                    'h3 a[href]'
                )
                if not link_tag:
                    continue

                raw_url = link_tag.get('href', '').strip()
                if not raw_url:
                    continue

                identifier = get_identifier(raw_url)
                clean_url = raw_url.split('#', 1)[0]

                price_span = item.select_one(
                    '.poly-price__current .andes-money-amount__fraction, '
                    '.ui-search-price__second-line .andes-money-amount__fraction, '
                    '.andes-money-amount__fraction'
                )

                items.append({
                    'identifier': identifier,
                    'title': link_tag.get_text(' ', strip=True),
                    'price': price_span.get_text(strip=True) if price_span else '0',
                    'url': clean_url,
                })
            except Exception as e:
                if self.debug:
                    print(f'Error parsing item: {e}')
                continue

        page_size = self._get_page_size(soup, items)
        next_url = self._next_url(
            current_url=body.get('url', self.url),
            items_on_page=len(items),
            page_size=page_size,
            soup=soup,
        )

        return items, next_url

    def _get_page_size(self, soup: BeautifulSoup, items: list) -> int:
        try:
            script = soup.find('script', id='__NEXT_DATA__')
            if script:
                data = json.loads(script.string)
                return data["props"]["pageProps"]["initialState"]["melidata_track"]["event_data"]["limit"]
        except Exception:
            pass
        return len(items) if items else 50

    def _next_url(self, current_url: str, items_on_page: int, page_size: int, soup: BeautifulSoup):
        if items_on_page < page_size:
            return None
        if not self._has_next_page(soup):
            return None
        next_offset = self._next_offset(current_url, page_size)
        return self._inject_offset(current_url, next_offset)

    def _has_next_page(self, soup: BeautifulSoup) -> bool:
        next_a = soup.select_one(
            'li.andes-pagination__button--next a[title="Siguiente"], '
            'li.andes-pagination__button--next a[data-andes-pagination-control="next"]'
        )
        if not next_a:
            return False
        next_li = next_a.find_parent('li', class_=re.compile(r'andes-pagination__button--next'))
        if next_li and 'andes-pagination__button--disabled' in (next_li.get('class') or []):
            return False
        return True

    def _next_offset(self, current_url: str, page_size: int) -> int:
        match = re.search(r'_Desde_(\d+)', current_url)
        if match:
            return int(match.group(1)) + page_size
        return page_size + 1

    def _inject_offset(self, current_url: str, next_offset: int) -> str:
        from urllib.parse import urlparse, urlunparse
        parsed = urlparse(current_url)
        path = parsed.path

        if re.search(r'_Desde_\d+', path):
            path = re.sub(r'_Desde_\d+', f'_Desde_{next_offset}', path, count=1)
        elif path.startswith('/_CustId_'):
            path = f'/_Desde_{next_offset}{path[1:]}'
        elif '_NoIndex_True' in path:
            path = path.replace('_NoIndex_True', f'_Desde_{next_offset}_NoIndex_True', 1)
        else:
            path = f'{path}_Desde_{next_offset}'

        return urlunparse((parsed.scheme, parsed.netloc, path, parsed.params, parsed.query, parsed.fragment))