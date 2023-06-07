from bs4 import BeautifulSoup

from scraper.motor import Motor
from .article import Article

import json
import re
from traceback import format_exc

class Liverpool(Motor):
    def __init__(self, search_term: str, url: str):
        super().__init__(search_term, url)


    def scrape_page(self, body):
        items = list()
        next_url = None
        records = []

        soup = BeautifulSoup(body['content'], 'html.parser')
        root = soup.find('script', id='__NEXT_DATA__')
        page_object = json.loads(root.string)
        records = page_object['query']['data']['mainContent']['records']
        for record in records:
            item = record['allMeta']
            args = {}
            args['identifier'] = item['id']
            args['title'] = item['title']
            args['price'] = item['minimumPromoPrice']
            #args['priceMax'] = item['maximumPromoPrice']
            formated_title = item['title'].lower().replace(" ", "-")
            identifier = item['id']
            args['url'] = f'https://www.liverpool.com.mx/tienda/pdp/{formated_title}/{identifier}'
            args['search_term'] = self.search_term
            #print(str(args))
            items.append(args)
        try:
            noOfPages = int(page_object['query']['data']['mainContent']['pageInfo']['noOfPages'])
            pattern = r"/page-(\d+)$"
            matches = re.findall(pattern, body['url'])
            
            currentPage = int(matches[-1]) if matches else 1
            next_page = currentPage + 1
            
            if currentPage < noOfPages:
                next_url = f'{self.url}/page-{next_page}'
        except:
            print(format_exc())
            pass
        
        return items, next_url
    
    def is_article(self, article) -> bool:
        return isinstance(article, Article)

    def create_article(self, article: dict) -> Article:
        return Article.create(article)