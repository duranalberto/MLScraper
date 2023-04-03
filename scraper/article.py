from datetime import datetime as datatime_lib
from .status import Status
prefix = 'https://articulo.mercadolibre.com.mx/'

class Article:
    def __init__(self, search_term, identifier, title, price, datetime = None,  status: Status = Status.none):
        self.search_term = search_term
        self.identifier = identifier
        self.title = title
        self.price = price
        self.datetime = datetime if datetime else str(datatime_lib.now())
        self.status = status
    
    def __str__(self):
        return '[' + str(self.datetime)  + '] - ' + prefix + self.identifier + '  ->  ' + self.title + '  $' + self.price
    
    def __repr__(self):
        return self.identifier

    def __hash__(self):
        return hash(self.identifier)

    def __eq__(self, other):
        if isinstance(other, Article):
            return self.identifier == other.identifier
        return NotImplemented

    def dump(self):
        return {
                'search_term': self.search_term,
                'url': prefix + self.identifier,
                'identifier': self.identifier,
                'title': self.title,
                'price': self.price,
                'datetime': str(self.datetime),
                'status': self.status
               }
    
    @staticmethod
    def is_valid_args(args: dict):
        if not isinstance(args, dict):
            return None
        if not 'search_term' in args or  not 'identifier' in args or not 'title' in args  or not 'price' in args:
            return False
        if len(args['identifier']) < 10 or len(args['identifier']) > 25:
            return False
        return True

    @staticmethod
    def create(args: dict):
        if not Article.is_valid_args(args):
            return None
        if not 'datetime' in args:
            args['datetime'] = None
        if not 'status' in args:
            args['status'] = Status.none
        return Article(args['search_term'], args['identifier'], args['title'], args['price'], args['datetime'], args['status'])