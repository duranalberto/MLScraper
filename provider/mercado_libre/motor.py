import logging
import re
import json
from bs4 import BeautifulSoup
from scraper.motor import Motor
from .utils import Category, get_identifier, construct_search_url

logger = logging.getLogger(__name__)


class MercadoLibre(Motor):
    def __init__(self, search_term: str, category: Category = Category.consolas_videojuegos, *, storage_path: str):
        super().__init__(search_term, construct_search_url(search_term, category), storage_path=storage_path)

    def scrape_page(self, body):
        items = []
        next_url = None

        html = body.get('content', '')
        soup = BeautifulSoup(html, 'html.parser')

        if self._is_account_verification_page(soup):
            self._scrape_incomplete = True
            if self.debug:
                logger.warning(
                    "Mercado Libre is requesting account verification for '%s' at %s.",
                    self.search_term,
                    body.get('url', self.url),
                )
            return items, None

        root = soup.find('section', class_='ui-search-results')
        if not root:
            self._scrape_incomplete = True
            return items, None

        raw_items = root.select('ol.ui-search-layout > li.ui-search-layout__item')

        for item in raw_items:
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
                
                raw_price = price_span.get_text(strip=True) if price_span else '0'
                price_str = raw_price.replace(',', '').strip()
                try:
                    price_val = float(price_str) if price_str else 0.0
                except ValueError:
                    price_val = 0.0

                items.append({
                    'identifier': identifier,
                    'title': link_tag.get_text(' ', strip=True),
                    'price': price_val,
                    'url': clean_url,
                })
            except Exception as e:
                if self.debug:
                    logger.exception("Error parsing item in '%s': %s", self.search_term, e)
                continue

        page_size = self._get_page_size(soup, len(raw_items))
        next_url = self._next_url(
            current_url=body.get('url', self.url),
            items_on_page=len(raw_items),
            page_size=page_size,
            soup=soup,
        )

        return items, next_url

    def _get_page_size(self, soup: BeautifulSoup, raw_item_count: int) -> int:
        try:
            script = soup.find('script', id='__NEXT_DATA__')
            if script:
                data = json.loads(script.string)
                return data["props"]["pageProps"]["initialState"]["melidata_track"]["event_data"]["limit"]
        except Exception:
            pass
        return raw_item_count if raw_item_count else 50

    def _next_url(self, current_url: str, items_on_page: int, page_size: int, soup: BeautifulSoup):
        if items_on_page <= 0:
            return None
        if not self._has_next_page(soup):
            return None
        total_results = self._total_results(soup)
        if total_results is not None:
            current_offset = self._current_offset(current_url)
            if current_offset + items_on_page >= total_results:
                return None
        elif items_on_page < page_size:
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

    @staticmethod
    def _current_offset(current_url: str) -> int:
        match = re.search(r'_Desde_(\d+)', current_url)
        if match:
            try:
                return int(match.group(1))
            except ValueError:
                return 0
        return 0

    def _total_results(self, soup: BeautifulSoup) -> int | None:
        text = soup.get_text(" ", strip=True).lower()
        patterns = (
            r'(\d[\d.,]*)\s+resultados?',
            r'(\d[\d.,]*)\s+publicaciones?',
            r'(\d[\d.,]*)\s+art[íi]culos?',
            r'(\d[\d.,]*)\s+productos?',
        )
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                number = re.sub(r"[^\d]", "", match.group(1))
                if number:
                    try:
                        return int(number)
                    except ValueError:
                        continue
        return None

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

    @staticmethod
    def _is_account_verification_page(soup: BeautifulSoup) -> bool:
        html = str(soup).lower()
        if 'account-verification' in html or 'suspicious-traffic' in html:
            return True

        text = soup.get_text(' ', strip=True).lower()
        return 'ingresa a tu cuenta' in text and 'mercado libre' in text
