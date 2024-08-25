from scraper.article import Article as BaseArticle

class Article(BaseArticle):
    def is_valid_args(args: dict) -> bool:
        if not isinstance(args, dict):
            return False
        if not 'search_term' in args or not 'identifier' in args or not 'title' in args  or not 'price' in args:
            return False
        if len(args['identifier']) < 10 or len(args['identifier']) > 25:
            return False
        return True