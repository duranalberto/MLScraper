import json
import aiohttp
import traceback
from bs4 import BeautifulSoup

from stream import Stream
from models.Category import Category
from models.Article import Article
from models.Status import Status
import utils

headers = { 
	'authority': 'httpbin.org', 
	'cache-control': 'max-age=0', 
	'sec-ch-ua': '"Chromium";v="92", " Not A;Brand";v="99", "Google Chrome";v="92"', 
	'sec-ch-ua-mobile': '?0', 
	'upgrade-insecure-requests': '1', 
	'user-agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/92.0.4515.107 Safari/537.36', 
	'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9', 
	'sec-fetch-site': 'none', 
	'sec-fetch-mode': 'navigate', 
	'sec-fetch-user': '?1', 
	'sec-fetch-dest': 'document', 
	'accept-language': 'en-US,en;q=0.9', 
}

class Manager:
    def __init__(self, search_term: str, category: Category = Category.none):
        self.search_term = search_term
        self.category = category
        self.file_name = search_term + '.json'
        self.active = Stream(Status.active)
        self.finished = Stream(Status.finished)
        self.load_from_file()


    async def scrape(self, caller = None, silent: bool = False):
        results = list()
        url = utils.construct_search_url(self.search_term, self.category)
        try:
            async with aiohttp.ClientSession() as session:
                while url is not None:
                    async with session.get(url, headers=headers) as resp:
                        body = await resp.text()
                        items, url = self.__scrape_page(body)
                        for item in items:
                            article, is_new = self.save(item)
                            if isinstance(article, Article):
                                results.append(article)
                                if is_new and caller is not None:
                                    await caller(article.dump())
            if len(results) > 1:
                if not silent:
                    print('Total articles recorded for ' + self.search_term + ': ' + str(len(results)))
                deleted_articles = self.active - results
                for deleted in deleted_articles:
                    self.save(deleted, to_status = Status.finished)
                await self.save_to_file()
        except Exception:
            print("Loading for " + self.search_term + " failed!")
            print(traceback.format_exc())


    def __scrape_page(self, body):
        items = list()
        next_url = None

        soup = BeautifulSoup(body, 'html.parser')
        root = soup.find("section", class_="ui-search-results ui-search-results--without-disclaimer shops__search-results")
        item_ol = root.find("ol", class_="ui-search-layout ui-search-layout--stack shops__layout").find_all("li", class_="ui-search-layout__item shops__layout-item")
        for item in item_ol:
            item_a_tag = item.find("a", class_="ui-search-item__group__element shops__items-group-details ui-search-link", href=True)
            args = {}
            args['identifier']  = utils.get_identifier(item_a_tag['href'])
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
            
    

    def print_compare(self):
        print('\nResume for: ' + self.search_term)
        print('Elements in file:    ' + str(len(self.active + self.finished)))
        print('New elements found:  ' + str(len(self.active.get_list())))
        print('Elements lost:       ' + str(len(self.finished.get_list())))
        for article in self.active.get_list():
            print(article)
    

    def get_all(self):
        return self.active + self.finished
    

    def clear_all_streams(self):
        self.active.clear()
        self.finished.clear()
    

    def save(self, article: dict | Article, to_status: Status = Status.none, at_beginning = True):
        is_new = False
        if not isinstance(article, Article):
            article = Article.create(article)
        if article is None:
            return None, is_new
        status = to_status
        if status is Status.none:
            status = article.status if article.status is not Status.none else Status.active
        
        if status == Status.active:
            deleted = self.finished.delete(article)
            at_beginning = at_beginning if deleted is None else False
            added = self.active.add(article if deleted is None else deleted, at_beginning)
            if deleted is None and isinstance(added, Article):
                is_new = True
        elif status == Status.finished:
            deleted = self.active.delete(article)
            self.finished.add(article if deleted is None else deleted)
        return article, is_new
    

    def load_from_file(self):
        json_array = utils.read_json_file(self.file_name)
        for json_object in json_array:
            json_object['search_term'] =  self.search_term
            self.save(json_object, at_beginning = False)


    async def save_to_file(self):
        self.active.order_by_time()
        self.finished.order_by_time()
        _list = self.get_all()
        json_string = json.dumps([article.dump() for article in _list], indent=2)
        await utils.write_in_file(self.file_name, json_string)