from .status import Status
from .article import Article

class Stream:
    def __init__(self, status: Status = Status.none, _list = None):
        self.status = status
        self._list = _list if _list else []

    def __bool__(self):
        return len(self._list) > 0

    def __add__(self, other):
        return self._list + other.get_list()

    def __sub__(self, other):
        return list(set(self._list).difference(other))

    def add(self, article: Article, at_beginning = False):
        if article:
            article.status = self.status
            if not article in self._list:
                if at_beginning:
                    self._list.insert(0, article)
                else:
                    self._list.append(article)
                return article
        return None

    def extend(self, _list):
        for article in _list:
            self.add(article)

    def delete(self, article: Article):
        if article in self._list:
            to_remove = self._list[self._list.index(article)]
            self._list.remove(to_remove)
            return to_remove
        return None

    def clear(self):
        self._list.clear()

    def print_len(self):
        print(str(len(self._list)))

    def print_(self):
        for e in self._list:
            print(e.title + ' - ' + str(e.status))

    def get_list(self):
        return self._list

    def order_by_time(self):
        self._list.sort(key=lambda x: x.datetime, reverse=True)
