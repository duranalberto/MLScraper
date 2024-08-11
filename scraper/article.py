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
    
    def dump(self) -> dict:
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
        
        is_valid = ('datetime' in args and args['datetime'] is not None) and ('title' in args or 'price' in args)
        title = args['title'] if 'title' in args else None
        price = args['price'] if 'price' in args else None
        return ArticleHistory(datetime= args['datetime'], title= title, price= price) if is_valid else None


class Article:
    def __init__(self, search_term, identifier, title, price, url:str = None, datetime = None, last_updated = None, status: Status = Status.none, history: list = list()):
        self.search_term = search_term
        self.identifier = identifier
        self.title = title
        self.price = price
        self.url = url
        self.datetime = datetime if datetime else str(datatime_lib.now())
        self.status = status
        self.history: List[ArticleHistory] = self.load_history(history)
        self.last_updated = last_updated if last_updated else None
    
    def __str__(self):
        return '[' + str(self.datetime)  + '] - ' + 'to_add' + '  ->  ' + self.title + '  $' + self.price + ' datetime ' + self.datetime
    
    def __repr__(self):
        return self.identifier

    def __hash__(self):
        return hash(self.identifier)

    def __eq__(self, other):
        if isinstance(other, Article):
            return self.identifier == other.identifier
        return NotImplemented

    def load_history(self, to_load, fix: bool= False) -> List[ArticleHistory]:
        history = list()

        if to_load is not None:
            for e in to_load:
                ah = ArticleHistory.create(e)
                if ah is not None:
                    history.append(ah)
        # TODO: This is a fix to update files, it should be added when the data is created
        if fix:
            if len(history) == 1:
                history[0].datetime = self.datetime
            elif len(history) > 1:
                history.sort(key=lambda x: x.datetime, reverse=True)
                history[-1].datetime = self.datetime
        return history

    def update(self, to_update: dict) -> bool:
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
            is_first_update = len(self.history) == 0
            data['datetime'] = self.datetime if is_first_update else self.last_updated
            ah = ArticleHistory.create(data)
            if(ah is not None):
                self.last_updated = str(datatime_lib.now())
                self.history.insert(0, ah)
                return True
        return False
    
    def dump(self) -> dict:
        dump = {
                'search_term': self.search_term,
                'url': self.url,
                'identifier': self.identifier,
                'title': self.title,
                'price': self.price,
                'datetime': str(self.datetime),
                'status': self.status,
               }
        dump_history = [ah.dump() for ah in self.history]
        if len(dump_history) > 0:
            dump['last_updated'] = self.last_updated
            dump['history'] = dump_history
        return dump 
    
    @staticmethod
    def is_valid_args(args: dict):
        if not isinstance(args, dict):
            return None
        if not 'search_term' in args or not 'url' in args or not 'identifier' in args or not 'title' in args  or not 'price' in args:
            return False
        return True

    @staticmethod
    def create(args: dict):
        if not Article.is_valid_args(args):
            return None
        if not 'datetime' in args:
            args['datetime'] = None
        if not 'last_updated' in args:
            args['last_updated'] = None
        if not 'status' in args:
            args['status'] = Status.none
        if not 'history' in args:
            args['history'] = None
        return Article(args['search_term'], args['identifier'], args['title'], args['price'], url= args['url'], datetime= args['datetime'],
                        last_updated= args['last_updated'], status= args['status'], history= args['history'])