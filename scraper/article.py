from abc import ABC, abstractmethod
from datetime import datetime as datatime_lib

from .status import Status

class Article(ABC):
    def __init__(self, search_term, identifier, title, price, datetime = None,  status: Status = Status.none):
        self.search_term = search_term
        self.identifier = identifier
        self.title = title
        self.price = price
        self.datetime = datetime if datetime else str(datatime_lib.now())
        self.status = status
    
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

    @abstractmethod
    def dump(self) -> dict():
        pass
    
    @staticmethod
    @abstractmethod
    def is_valid_args(args: dict):
        pass

    @staticmethod
    @abstractmethod
    def create(args: dict):
        pass