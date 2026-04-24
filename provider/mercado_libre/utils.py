import re
import unicodedata
import urllib.parse
from enum import Enum

_urls = {
    'article_prefix': 'https://articulo.mercadolibre.com.mx/',
    'catalog_prefix': 'https://www.mercadolibre.com.mx/up/',
    'base_search': 'https://listado.mercadolibre.com.mx',
}


class Category(Enum):
    none = ''
    consolas = '/consolas-videojuegos/consolas/nintendo/usado/'
    videojuegos = '/consolas-videojuegos/videojuegos/'
    consolas_videojuegos = '/consolas-videojuegos/'
    deportes_jersey = '/deportes-fitness/futbol/'

    iphone_trece_pro_usado = 'https://listado.mercadolibre.com.mx/celulares-telefonia/celulares-smartphones/usados/iphone-13-pro_NoIndex_True'
    iphone_once_pro_usado = 'https://listado.mercadolibre.com.mx/celulares-telefonia/celulares-smartphones/usados/iphone-11-pro_NoIndex_True'
    iphone_se_usado = 'https://listado.mercadolibre.com.mx/celulares-telefonia/celulares-smartphones/usados/iphone-se_NoIndex_True'

    apple_official = '_CustId_527927603_BRAND_9344_NoIndex_True'


def _slugify(term: str) -> str:
    term = unicodedata.normalize('NFKD', term or '')
    term = term.encode('ascii', 'ignore').decode('ascii')
    term = term.lower().strip()
    term = re.sub(r'[^a-z0-9]+', '-', term)
    return re.sub(r'-+', '-', term).strip('-')


def get_identifier(url: str) -> str:
    if not url:
        return ''

    parsed = urllib.parse.urlparse(url)
    qs = urllib.parse.parse_qs(parsed.query)

    wid = qs.get('wid', [''])[0]
    if wid:
        return wid

    match = re.search(r'/up/(MLMU\d+)', url)
    if match:
        return match.group(1)

    match = re.search(r'/p/(MLM\d+)', url)
    if match:
        return match.group(1)

    match = re.search(r'(MLM-?\d+|MLMU\d+)', url)
    if match:
        return match.group(1)

    return url


def construct_url_from_identifier(identifier: str) -> str:
    if not identifier:
        return ''

    if identifier.startswith('MLMU'):
        return f"{_urls['catalog_prefix']}{identifier}"

    return f"{_urls['article_prefix']}{identifier}"


def construct_search_url(search_term: str, category: Category = Category.none) -> str:
    base = _urls['base_search']

    hardcoded_categories = {
        Category.iphone_trece_pro_usado,
        Category.iphone_once_pro_usado,
        Category.iphone_se_usado,
    }

    if category in hardcoded_categories:
        return category.value

    slug = _slugify(search_term)

    if category == Category.apple_official:
        path = f"{slug}_{category.value}"
        return f"{base}/{path}?sb=seller_id#D[A:{slug}]"

    if category == Category.none:
        return f"{base}/{slug}_NoIndex_True"

    category_path = category.value.rstrip('/')
    return f"{base}{category_path}/{slug}_NoIndex_True"