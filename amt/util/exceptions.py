import time


class MatureContentException(Exception):
    pass


class ChapterLimitException(Exception):
    def __init__(self, reset_time, abs_limit):
        super().__init__(f"You've downloaded {abs_limit} chapters; Wait {(reset_time - time.time())/3600 :.2f}hrs for the limit to reset")
