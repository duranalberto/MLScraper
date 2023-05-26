from scraper.article import Article as BaseArticle
from scraper.status import Status
from .search_utils import construct_url_from_identifier
import json

class Article(BaseArticle):
    def __str__(self):
        return '[' + str(self.datetime)  + '] - ' + construct_url_from_identifier(self.identifier) + '  ->  ' + self.title + '  $' + self.price + ' datetime ' + self.datetime
    
    def dump(self) -> dict():
        dump = {
                'search_term': self.search_term,
                'url': construct_url_from_identifier(self.identifier),
                'identifier': self.identifier,
                'title': self.title,
                'price': self.price,
                'datetime': str(self.datetime),
                'last_updated': self.last_updated,
                'status': self.status,
               }
        dump_history = [ah.dump() for ah in self.history]
        if len(dump_history) > 0:
            dump['history'] = dump_history
        return dump 
    
    def is_valid_args(args: dict):
        if not isinstance(args, dict):
            return None
        if not 'search_term' in args or  not 'identifier' in args or not 'title' in args  or not 'price' in args:
            return False
        if len(args['identifier']) < 10 or len(args['identifier']) > 25:
            return False
        return True

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
        return Article(args['search_term'], args['identifier'], args['title'], args['price'], datetime= args['datetime'],
                        last_updated= args['last_updated'], status= args['status'], history= args['history'])