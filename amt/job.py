import logging
import traceback

from queue import Queue
from threading import Thread


class RetryException(Exception):
    retry_count = 1
    pass


class ItemWrapper():
    def __init__(self, item):
        self.item = item


class Job:
    def __init__(self, numThreads, iterable=[], func=None, raiseException=False):
        self.numThreads = numThreads
        self.queue = Queue()
        self.exception = None
        self.results = []
        self.func = func
        self.enqueue(iterable)
        self.raiseException = raiseException

    def enqueue(self, iterable):
        for item in iterable:
            self.add(item)

    def add(self, item):
        self.queue.put(item)

    def worker(self):
        while not self.queue.empty():
            item = self.queue.get()
            func = item if not isinstance(item, ItemWrapper) else item.item
            try:
                if func:
                    ret = func() if not self.func else self.func(func)
                    self.results.append(ret) if not isinstance(ret, list) else self.results.extend(ret)
            except Exception as e:
                if isinstance(e, RetryException) and not isinstance(item, ItemWrapper):
                    if e.retry_count > 0:
                        e.retry_count -= 1
                        self.add(ItemWrapper(func))
                        logging.info("Retry: '%s'; Readding item into queue", e)
                        continue

                self.exception = e
                logging.error(e)
                traceback.print_exc()
            finally:
                self.queue.task_done()

    def run(self):
        logging.info("Using %s threads for ~%d items", self.numThreads, self.queue.qsize())
        if self.numThreads:
            for i in range(self.numThreads):
                Thread(target=self.worker, daemon=True).start()
            self.queue.join()
        else:
            self.worker()
        if self.exception:
            logging.error("Error occurred: %s", self.exception)
            if self.raiseException:
                raise self.exception
        return self.results
