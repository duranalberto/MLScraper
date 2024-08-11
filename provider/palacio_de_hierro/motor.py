from bs4 import BeautifulSoup

from scraper.motor import Motor
from .article import Article

class PalacioDeHierro(Motor):
    def __init__(self, search_term: str, url: str):
        super().__init__(search_term, url)


    def scrape_page(self, body):
        items = list()
        next_url = None

        soup = BeautifulSoup(body['content'], 'html.parser')
        root = soup.find("section", class_="l-plp-grid_wrapper")
        items_div = root.find("section", class_="l-plp-grid_wrapper-products").find_all("article", class_="l-plp-grid_item m-product")
        for item in items_div:
            args = {}
            a = item.find("h3", class_="b-product_tile-name").find("a")
            url = a.get('href').strip()
            url = f'https://www.elpalaciodehierro.com{url}'
            args['identifier']  = item.attrs["data-pid"].strip()
            args['url']         = url
            args['title']       = a.text.replace('\n', '').strip()
            
            price_parent_tag = item.find("div", class_="b-product_price")
            price_tag = price_parent_tag.find("div", class_="b-product_price-sales m-reduced")
            if(price_tag is None):
                price_tag = price_parent_tag.find("div", class_="b-product_price-sales")
            price = price_tag.find("span", class_="b-product_price-value", text=True).text.replace('\n', '')

            args['price']       = float(price.replace('\n', '').replace('$','').replace(',','').strip())
            args['search_term'] = self.search_term
            items.append(args)
        try:
            next_a_tag = soup.find("li", class_="b-pagination-elements_list b-next-btn").find("a", class_="b-pagination-elements_number", href=True)
            next_url = next_a_tag['href']
        except:
            pass
        
        return items, next_url
    
    def is_article(self, article) -> bool:
        return isinstance(article, Article)

    def create_article(self, article: dict) -> Article:
        return Article.create(article)