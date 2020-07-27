#! /usr/bin/python
import logging
from amt.args import parse_args


if __name__ == "__main__":
    logging.basicConfig(format='[%(filename)s:%(lineno)s - %(funcName)20s()]%(levelname)s:%(message)s', level=logging.INFO)
    parse_args()
