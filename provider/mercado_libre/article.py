"""
MercadoLibre-specific Article validation.

ML identifiers look like:  MLM1234567890  or  MLMU1234567890
Typical length: 13–16 characters.
"""

from scraper.article import Article as BaseArticle


class Article(BaseArticle):
    @staticmethod
    def is_valid_args(args: dict) -> bool:
        if not BaseArticle.is_valid_args(args):
            return False
        identifier = args.get("identifier", "")
        # ML identifiers are 10–25 chars and start with MLM
        return 10 <= len(identifier) <= 25 and str(identifier).upper().startswith("MLM")
