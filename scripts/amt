#! /usr/bin/python
# PYTHON_ARGCOMPLETE_OK
import logging
from signal import SIG_DFL, SIGPIPE, signal

from amt.args import parse_args

if __name__ == "__main__":
    logging.basicConfig(format='[%(filename)s:%(lineno)s]%(levelname)s:%(message)s', level=logging.INFO)
    signal(SIGPIPE, SIG_DFL)
    parse_args()
