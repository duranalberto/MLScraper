from enum import Enum

_urls = {
    'article_prefix': 'https://articulo.mercadolibre.com.mx/',
    'url_search': 'https://listado.mercadolibre.com.mx|0|/usado/|1|_NoIndex_True'
}

class Category(Enum):
    none = ''
    consolas = '/consolas-videojuegos/consolas'
    videojuegos = '/consolas-videojuegos/videojuegos'
    consolas_videojuegos = '/consolas-videojuegos'
    deportes_jersey = '/deportes-fitness/futbol'

def get_identifier(url: str) -> str:
    if not url:
        return ''
    if url.startswith(_urls['article_prefix']):
        url = url[len(_urls['article_prefix']):]
    pre_url = url[:url.find('-') + 1]
    post_url = url[len(pre_url):]
    return pre_url + post_url[:post_url.find('-')]

def construct_url_from_identifier(identifier: str) -> str:
    return _urls['article_prefix'] + identifier

def construct_search_url(search_term: str, category: Category = Category.none) -> str:
    url = _urls['url_search'].replace('|0|', category.value)
    return url.replace('|1|', search_term.replace(' ', '-'))