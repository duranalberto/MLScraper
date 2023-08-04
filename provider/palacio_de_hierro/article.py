from scraper.article import Article as BaseArticle
from scraper.status import Status
import json

class Article(BaseArticle):
    def __str__(self):
        return '[' + str(self.datetime)  + '] - ' + 'to_add' + '  ->  ' + self.title + '  $' + self.price + ' datetime ' + self.datetime
    
    def dump(self) -> dict():
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
    
    def is_valid_args(args: dict):
        if not isinstance(args, dict):
            return None
        if not 'search_term' in args or not 'url' in args or not 'identifier' in args or not 'title' in args  or not 'price' in args:
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
        return Article(args['search_term'], args['identifier'], args['title'], args['price'], url= args['url'], datetime= args['datetime'],
                        last_updated= args['last_updated'], status= args['status'], history= None)