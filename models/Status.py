from enum import Enum

class Status(str, Enum):
    none = 'none'
    active = 'active'
    finished = 'finished'
    ignoring = 'ignoring'