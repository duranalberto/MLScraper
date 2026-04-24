from typing import List, Optional
from .status import Status
from .article import Article

class Stream:
    def __init__(self, status: Status = Status.none, _list: Optional[List[Article]] = None):
        self.status = status
        self._list: List[Article] = _list if _list else []

    def __iter__(self):
        """Allows: for article in stream:"""
        return iter(self._list)

    def __contains__(self, item):
        """Allows: if article in stream:"""
        return item in self._list

    def __len__(self):
        """Allows: len(stream)"""
        return len(self._list)

    def __bool__(self):
        """Allows: if stream:"""
        return len(self._list) > 0

    def __add__(self, other):
        """Allows: combined = stream1 + stream2"""
        if isinstance(other, Stream):
            return self._list + other.get_list()
        return self._list + list(other)

    def __sub__(self, other):
        """
        Allows: delta = stream_a - list_of_articles
        Returns a list of items in self that are NOT in other.
        """
        other_list = other.get_list() if isinstance(other, Stream) else other
        return [item for item in self._list if item not in other_list]

    def add(self, article: Article, at_beginning: bool = False) -> Optional[Article]:
        if article:
            article.status = self.status
            if article not in self._list:
                if at_beginning:
                    self._list.insert(0, article)
                else:
                    self._list.append(article)
                return article
        return None
    
    def update(self, article: Article) -> Optional[Article]:
        """Updates an existing article in the stream if title or price changed."""
        if article and article in self._list:
            index = self._list.index(article)
            target = self._list[index]
            # Assumes Article.update returns True if data actually changed
            was_updated = target.update({'title': article.title, 'price': article.price})
            return target if was_updated else None
        return None

    def extend(self, _list: List[Article]):
        for article in _list:
            self.add(article)

    def delete(self, article: Article) -> Optional[Article]:
        if article in self._list:
            to_remove = self._list[self._list.index(article)]
            self._list.remove(to_remove)
            return to_remove
        return None

    def clear(self):
        self._list.clear()

    def get_list(self) -> List[Article]:
        return self._list

    def order_by_time(self):
        """Sorts articles by datetime attribute in descending order."""
        self._list.sort(key=lambda x: x.datetime, reverse=True)

    def print_(self):
        for e in self._list:
            print(f"{e.title} - {e.status}")