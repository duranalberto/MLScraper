from bs4 import BeautifulSoup
from enum import Enum

from scraper.motor import Motor

class Category(Enum):
    none = ''
    consolas = 'consolas'
    videojuegos = 'videojuegos'

class MercadoLibre(Motor):
    def __init__(self, search_term: str, category: Category = Category.none):
        super().__init__(search_term, construct_search_url(search_term, category))


    def scrape_page(self, body):
        items = list()
        next_url = None

        soup = BeautifulSoup(body, 'html.parser')
        root = soup.find("section", class_="ui-search-results ui-search-results--without-disclaimer shops__search-results")
        item_ol = root.find("ol", class_="ui-search-layout ui-search-layout--stack shops__layout").find_all("li", class_="ui-search-layout__item shops__layout-item")
        for item in item_ol:
            item_a_tag = item.find("a", class_="ui-search-item__group__element shops__items-group-details ui-search-link", href=True)
            args = {}
            args['identifier']  = get_identifier(item_a_tag['href'])
            args['title']       = item.find("h2", class_="ui-search-item__title shops__item-title", text=True).text
            args['price']       = item.find("span", class_="price-tag-amount").find("span", class_="price-tag-fraction", text=True).text
            args['search_term'] = self.search_term
            items.append(args)
        try:
            next_a_tag = root.find("li", class_="andes-pagination__button andes-pagination__button--next shops__pagination-button").find("a", class_="andes-pagination__link shops__pagination-link ui-search-link", href=True)
            next_url = next_a_tag['href']
        except:
            pass
        
        return items, next_url

url_article_prefix = 'https://articulo.mercadolibre.com.mx/'
url_search = 'https://listado.mercadolibre.com.mx/consolas-videojuegos/|0|usado/|1|_NoIndex_True'


def get_identifier(url: str) -> str:
    if not url:
        return ''
    if url.startswith(url_article_prefix):
        url = url[len(url_article_prefix):]
    pre_url = url[:url.find('-') + 1]
    post_url = url[len(pre_url):]
    return pre_url + post_url[:post_url.find('-')]

def construct_url_from_identifier(identifier: str) -> str:
    return url_article_prefix + identifier

def construct_search_url(search_term: str, category: Category = Category.none) -> str:
    url = url_search.replace('|0|', category.value + '/' if category is not Category.none else '')
    return url.replace('|1|', search_term.replace(' ', '-'))