from abc import ABC, abstractmethod
from aiohttp import ClientSession
from asyncio import gather
from json import dumps as json_dumps
from typing import Optional, Tuple

from .stream import Stream
from .article import Article
from .status import Status

from utils.file_manager import read_json_file, write_in_file
from utils.headers import headers

from traceback import format_exc
 
class Motor(ABC):
    def __init__(self, search_term: str, url: str, debug: bool = True):
        self.search_term = search_term
        self.url = url
        self.file_name = search_term + '.json'
        self.active = Stream(Status.active)
        self.finished = Stream(Status.finished)
        self.load_from_file()
        self.debug = debug

    async def scrape(self, caller = None, silent: bool = False):
        results = []
        url = self.url
        try:
            async with ClientSession() as session:
                while url:
                    async with session.get(url, headers=headers) as resp:
                        body = {'content': await resp.text(), 'url': url}
                        items, url = self.scrape_page(body)
                        for item in items:
                            article, is_new, is_updated = self.save(item)
                            if self.is_article(article):
                                results.append(article)
                                if is_new and caller:
                                    await caller(broadcast_type='new_element', element=article.dump())
                                if is_updated and caller:
                                    await caller(broadcast_type='is_updated', element=article.dump())

            if results:
                if not silent:
                    print(f'Total articles recorded for {self.search_term}: {len(results)}')
                deleted_articles = self.active - results
                for deleted in deleted_articles:
                    self.save(deleted, to_status = Status.finished)
                await self.save_to_file()
        except Exception:
            print(f"Loading for {self.search_term} failed!")
            if self.debug:
                print(format_exc())   

    @abstractmethod
    def scrape_page(self, body: dict) -> tuple[list, str]:
        pass

    def print_compare(self):
        print('\nResume for: ' + self.search_term)
        print('Elements in file:    ' + str(len(self.active + self.finished)))
        print('New elements found:  ' + str(len(self.active.get_list())))
        print('Elements lost:       ' + str(len(self.finished.get_list())))
        for article in self.active.get_list():
            print(article)

    def get_all(self) -> Stream:
        return self.active + self.finished

    def clear_all_streams(self):
        self.active.clear()
        self.finished.clear()

    def save(self, article: Optional[Article | dict], to_status: Status = Status.none, at_beginning = True) -> Tuple[Optional[Article], bool, bool]:
        is_new = False
        is_updated = False
        article = article if self.is_article(article) else self.create_article(article)

        if article:
            status = to_status if to_status else (article.status if article.status else Status.active)
            
            match status:
                case Status.active:
                    deleted = self.finished.delete(article)
                    at_beginning = at_beginning if deleted is None else False
                    added = self.active.add(article if deleted is None else deleted, at_beginning)
                    if deleted is None and self.is_article(added):
                        is_new = True
                    else:
                        article_updated = self.active.update(article)
                        if isinstance(article_updated, Article):
                            article = article_updated
                            is_updated = True
                case Status.finished:
                    deleted = self.active.delete(article)
                    self.finished.add(article if deleted is None else deleted)
        
        return article, is_new, is_updated

    def is_article(self, article) -> bool:
        return isinstance(article, Article)

    def create_article(self, article: dict) -> Optional[Article]:
        return Article.create(article)

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