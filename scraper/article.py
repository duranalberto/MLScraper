from dataclasses import dataclass, fields, field, MISSING
from datetime import datetime as datatime_lib
from typing import List, Self, Optional, Dict, Any

from .status import Status

@dataclass
class ArticleHistory:
    datetime: str
    title: Optional[str] = None
    price: Optional[str] = None

    def __str__(self) -> str:
        return f'[{self.datetime}] - {self.title}  ${self.price}'

    def dump(self) -> Dict[str, Any]:
        dump = {'datetime': self.datetime}
        if self.title:
            dump['tile'] = self.title
        if self.price:
            dump['price'] = self.price
        return dump

    @staticmethod
    def create(args: Dict[str, Any]) -> Optional[Self]:
        is_valid = 'datetime' in args and args['datetime'] and ('title' in args or 'price' in args)
        if not is_valid:
            return None

        return ArticleHistory(
            datetime=args['datetime'],
            title=args.get('title'),
            price=args.get('price')
        )


@dataclass
class Article:
    search_term: str
    identifier: str
    title: str
    price: float
    url: Optional[str] = None
    datetime: str = field(default_factory=lambda: str(datatime_lib.now()))
    status: Status = Status.none
    history: List[ArticleHistory] = field(default_factory=list)
    last_updated: Optional[str] = None

    def __post_init__(self):
        self.history = self.load_history(self.history)

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

        if to_load:
            for data in to_load:
                article_history = ArticleHistory.create(data)
                if article_history:
                    history.append(article_history)
        # TODO: This is a fix to update files, it should be added when the data is created
        if fix:
            if len(history) == 1:
                history[0].datetime = self.datetime
            elif len(history) > 1:
                history.sort(key=lambda x: x.datetime, reverse=True)
                history[-1].datetime = self.datetime
        return history

    def update(self, to_update: dict) -> bool:
        keys_to_update = ['title', 'price']
        changes = {key: getattr(self, key) for key in keys_to_update if key in to_update and getattr(self, key) != to_update[key]}

        for key in changes:
            setattr(self, key, to_update[key])
        
        if changes:
            is_first_update = not self.history
            changes['datetime'] = self.datetime if is_first_update else self.last_updated
            article_history  = ArticleHistory.create(changes)

            if article_history :
                self.last_updated = str(datatime_lib.now())
                self.history.insert(0, article_history)
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
        
        if self.history:
            dump['last_updated'] = self.last_updated
            dump['history'] = [ah.dump() for ah in self.history]
        
        return dump 
    
    @staticmethod
    def is_valid_args(args: Dict[str, Any]) -> bool:
        required_fields: set[str] = {f.name for f in fields(Article) if f.default is MISSING and f.default_factory is MISSING}
        missing_keys = required_fields - args.keys()
        return not missing_keys

    @staticmethod
    def create(args: dict) -> Optional[Self]:
        if not Article.is_valid_args(args):
            return None
        return Article(**args)