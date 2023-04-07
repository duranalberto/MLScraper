from scraper.article import Article as BaseArticle
from scraper.status import Status
from .search_utils import construct_url_from_identifier

class Article(BaseArticle):
    def __str__(self):
        return '[' + str(self.datetime)  + '] - ' + construct_url_from_identifier(self.identifier) + '  ->  ' + self.title + '  $' + self.price
    
    def dump(self) -> dict():
        return {
                'search_term': self.search_term,
                'url': construct_url_from_identifier(self.identifier),
                'identifier': self.identifier,
                'title': self.title,
                'price': self.price,
                'datetime': str(self.datetime),
                'status': self.status
               }
    
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
        if not 'status' in args:
            args['status'] = Status.none
        return Article(args['search_term'], args['identifier'], args['title'], args['price'], args['datetime'], args['status'])