import logging
import re
import json
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from scraper.motor import Motor
from .utils import Category, get_identifier, construct_search_url

logger = logging.getLogger(__name__)


class MercadoLibre(Motor):
    PROVIDER_KEY = "ml"

    def __init__(
        self,
        search_term: str,
        category: Category = Category.consolas_videojuegos,
        *,
        url: str | None = None,
        storage_path: str,
    ):
        super().__init__(search_term, url or construct_search_url(search_term, category), storage_path=storage_path)

    def scrape_page(self, body):
        items = []
        next_url = None

        html = body.get('content', '')
        soup = BeautifulSoup(html, 'html.parser')

        blocked_reason = self._blocked_page_reason(soup)
        if blocked_reason:
            self._scrape_incomplete = True
            self.mark_blocked(blocked_reason, self.BLOCKED_BACKOFF_SECONDS)
            if self.debug:
                logger.warning(
                    "Mercado Libre returned a blocked/gated page (%s) for '%s' at %s.",
                    blocked_reason,
                    self.search_term,
                    body.get('url', self.url),
                )
            return items, None

        items, next_url = self._parse_dom_results(soup, body.get('url', self.url))
        if not items:
            items, next_url = self._parse_nordic_state(soup)

        if not items:
            self._scrape_incomplete = True
            self.blocked_reason = "mercado_libre_results_root_missing"
            return items, None

        return items, next_url

    def _parse_dom_results(self, soup: BeautifulSoup, current_url: str):
        items = []
        next_url = None
        root = soup.find('section', class_='ui-search-results')
        if not root:
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
                cents_span = item.select_one(
                    '.poly-price__current .andes-money-amount__cents, '
                    '.ui-search-price__second-line .andes-money-amount__cents'
                )
                raw_cents = cents_span.get_text(strip=True) if cents_span else ''
                price_str = raw_price.replace(',', '').strip()
                if raw_cents:
                    price_str = f"{price_str}.{raw_cents.zfill(2)}"
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
            current_url=current_url,
            items_on_page=len(raw_items),
            page_size=page_size,
            soup=soup,
        )

        return items, next_url

    def _parse_nordic_state(self, soup: BeautifulSoup):
        state = self._nordic_initial_state(soup)
        if not state:
            return [], None

        items = []
        for result in state.get('results') or []:
            polycard = result.get('polycard') if isinstance(result, dict) else None
            if not isinstance(polycard, dict):
                continue
            metadata = polycard.get('metadata') or {}
            title = self._nordic_component_value(polycard, 'title', 'title', 'text')
            price = self._nordic_component_value(polycard, 'price', 'price', 'current_price', 'value')
            raw_url = self._nordic_url(metadata)
            identifier = metadata.get('user_product_id') or metadata.get('id') or get_identifier(raw_url)

            if not identifier or not title or price is None:
                continue

            try:
                price_val = float(price)
            except (TypeError, ValueError):
                price_val = 0.0

            items.append({
                'identifier': str(identifier),
                'title': str(title),
                'price': price_val,
                'url': raw_url.split('#', 1)[0],
            })

        pagination = state.get('pagination') or {}
        next_page = pagination.get('next_page') or {}
        next_url = next_page.get('url') if next_page.get('show') else None
        return items, next_url

    @staticmethod
    def _nordic_initial_state(soup: BeautifulSoup) -> dict | None:
        script = soup.find('script', id='__NORDIC_RENDERING_CTX__')
        body = (script.string or script.get_text()) if script else ''
        prefix = '_n.ctx.r='
        if not body.startswith(prefix):
            return None
        try:
            data, _ = json.JSONDecoder().raw_decode(body[len(prefix):])
            return data['appProps']['pageProps']['initialState']
        except (KeyError, TypeError, json.JSONDecodeError):
            return None

    @staticmethod
    def _nordic_component_value(polycard: dict, component_type: str, *path: str):
        for component in polycard.get('components') or []:
            if component.get('type') != component_type:
                continue
            value = component
            for key in path:
                if not isinstance(value, dict) or key not in value:
                    return None
                value = value[key]
            return value
        return None

    @staticmethod
    def _nordic_url(metadata: dict) -> str:
        raw_url = str(metadata.get('url') or '')
        if raw_url and not urlparse(raw_url).scheme:
            raw_url = f'https://{raw_url}'
        fragments = str(metadata.get('url_fragments') or '')
        if fragments and raw_url and '#' not in raw_url:
            raw_url = f'{raw_url}{fragments}'
        return raw_url

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
        return MercadoLibre._blocked_page_reason(soup) is not None

    @staticmethod
    def _blocked_page_reason(soup: BeautifulSoup) -> str | None:
        html = str(soup).lower()
        if 'account-verification' in html or 'suspicious-traffic' in html:
            return 'mercado_libre_account_verification'

        text = soup.get_text(' ', strip=True).lower()
        if 'this page requires javascript' in text or 'enable javascript' in text:
            return 'mercado_libre_js_required'
        if 'ingresa a tu cuenta' in text and 'mercado libre' in text:
            return 'mercado_libre_account_verification'
        return None
