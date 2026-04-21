"""
provider/mercado_libre/article.py

MercadoLibre-specific Article validation.

Previously this subclass validated that `search_term` was present and had
a plausible length (10–25 chars).  That field has been removed from Article
entirely (it belongs to the Motor, not individual records), so the only
remaining job is validating the MercadoLibre identifier format.

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