from enum import Enum

class Status(str, Enum):
    none = 'none'
    active = 'active'
    on_hold = 'on_hold'
    finished = 'finished'
    ignoring = 'ignoring'