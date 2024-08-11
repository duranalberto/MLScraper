from bs4 import BeautifulSoup

from scraper.motor import Motor
from .article import Article
from .search_utils import Category
from .search_utils import construct_search_url, get_identifier

class MercadoLibre(Motor):
    def __init__(self, search_term: str, category: Category = Category.consolas_videojuegos):
        super().__init__(search_term, construct_search_url(search_term, category))


    def scrape_page(self, body):
        items = list()
        next_url = None
        soup = BeautifulSoup(body['content'], 'html.parser')
        root = soup.find("section", class_="ui-search-results ui-search-results--without-disclaimer")
        item_ol = root.find("ol").find_all("li")
        for item in item_ol:
            item_a_tag = item.find("a", class_="ui-search-item__group__element ui-search-link__title-card ui-search-link", href=True)
            args = {}
            args['identifier']  = get_identifier(item_a_tag['href'])
            args['title']       = item.find("h2", class_="ui-search-item__title", text=True).text
            args['price']       = item.find("span", class_="andes-money-amount__fraction", text=True).text
            args['search_term'] = self.search_term
            items.append(args)
        try:
            next_a_tag = root.find("li", class_="andes-pagination__button andes-pagination__button--next").find("a", class_="andes-pagination__link", href=True)
            next_url = next_a_tag['href']
        except:
            pass
        
        return items, next_url
    
    def is_article(self, article) -> bool:
        return isinstance(article, Article)

    def create_article(self, article: dict) -> Article:
        return Article.create(article)