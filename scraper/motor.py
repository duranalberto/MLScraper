from abc import ABC, abstractmethod
from aiohttp import ClientSession
from json import dumps as json_dumps
from traceback import format_exc

from .stream import Stream
from .article import Article
from .status import Status

from utils.file_manager import read_json_file, write_in_file
from utils.headers import headers

 
class Motor(ABC):
    def __init__(self, search_term: str, url: str):
        self.search_term = search_term
        self.url = url
        self.file_name = search_term + '.json'
        self.active = Stream(Status.active)
        self.finished = Stream(Status.finished)
        self.load_from_file()


    async def scrape(self, caller = None, silent: bool = False):
        results = list()
        url = self.url
        try:
            async with ClientSession() as session:
                while url is not None:
                    async with session.get(url, headers=headers) as resp:
                        body = await resp.text()
                        items, url = self.scrape_page(body)
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
            print(format_exc())


    @abstractmethod
    def scrape_page(self, body):
        pass


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
        json_array = read_json_file(self.file_name)
        for json_object in json_array:
            json_object['search_term'] =  self.search_term
            self.save(json_object, at_beginning = False)


    async def save_to_file(self):
        self.active.order_by_time()
        self.finished.order_by_time()
        _list = self.get_all()
        json_string = json_dumps([article.dump() for article in _list], indent=2)
        await write_in_file(self.file_name, json_string)