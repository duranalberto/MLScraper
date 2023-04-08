from abc import ABC, abstractmethod
from datetime import datetime as datatime_lib
from typing import List

from .status import Status

class ArticleHistory:
    def __init__(self, datetime: str = None, title: str = None, price: str = None):
        self.datetime = datetime
        self.title = title
        self.price = price
    
    def __str__(self):
        return '[' + str(self.datetime)  + '] - ' + self.title + '  $' + self.price
    
    def dump(self) -> dict():
        e = {}
        e['datetime'] = self.datetime
        if(self.title is not None):
            e['title'] = self.title
        if(self.price is not None):
            e['price'] = self.price
        return e
    
    @staticmethod
    def create(args: dict):
        if(args is None):
            return None
        if('datetime' not in args or args['datetime'] is None):
            args['datetime'] = str(datatime_lib.now())
        is_valid = 'title' in args or 'price' in args
        title = args['title'] if 'title' in args else None
        price = args['price'] if 'price' in args else None
        return ArticleHistory(datetime= args['datetime'], title= title, price= price) if is_valid else None

class Article(ABC):
    def __init__(self, search_term, identifier, title, price, datetime = None, last_updated = None, status: Status = Status.none, history: list = list()):
        self.search_term = search_term
        self.identifier = identifier
        self.title = title
        self.price = price
        self.datetime = datetime if datetime else str(datatime_lib.now())
        self.last_updated = last_updated if last_updated else self.datetime
        self.status = status
        self.history: List[ArticleHistory] = self.load_history(history)
    
    @abstractmethod
    def __str__(self):
        pass
    
    def __repr__(self):
        return self.identifier

    def __hash__(self):
        return hash(self.identifier)

    def __eq__(self, other):
        if isinstance(other, Article):
            return self.identifier == other.identifier
        return NotImplemented

    def load_history(self, to_load) -> List[ArticleHistory]:
        history = list()
        if to_load is not None:
            for e in to_load:
                ah = ArticleHistory.create(e)
                if ah is not None:
                    history.append(ah)
        return history

    def update(self, to_update: dict, testing = False) -> bool:
        #print(self.identifier + ' ' + str(to_update))
        if('title' not in to_update and 'price' not in to_update):
            return False
        data = {}
        if('title' in to_update and self.title != to_update['title']):
            data['title'] = self.title
            self.title = to_update['title']
        if('price' in to_update  and self.price != to_update['price']):
            data['price'] = self.price
            self.price = to_update['price']
        if(len(data) > 0):
            ah = ArticleHistory.create(data)
            if(ah is not None):
                self.history.append(ah)
                self.last_updated = ah.datetime
                return True
        return False

    @abstractmethod
    def dump(self) -> dict:
        pass
    
    @staticmethod
    @abstractmethod
    def is_valid_args(args: dict):
        pass

    @staticmethod
    @abstractmethod
    def create(args: dict):
        pass