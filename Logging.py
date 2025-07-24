import sys
from enum import Enum


class Severity(Enum):
    FATAL = 0
    WTF = 1
    ERROR = 2
    INFO = 3
    DEBUG = 4

severity_limit = Severity.INFO

def get_caller():
    logging_frame_globals = sys._getframe(2).f_globals
    if 'LOGGING_NAME' in logging_frame_globals:
        return logging_frame_globals['LOGGING_NAME']
    return logging_frame_globals['__name__']

def log(message, severity=Severity.INFO):
    if severity.value > severity_limit.value:
        return
    caller = get_caller()
    print(f'[{severity.name}][{caller}] {message}')
