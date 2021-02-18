import logging
import traceback
from collections import deque
from queue import Queue
from threading import Thread


class Job:
    def __init__(self, numThreads, iterable=[], raiseException=False):
        self.numThreads = numThreads
        self.queue = Queue()
        self.exception = None
        self.results = deque()
        self.enqueue(iterable)
        self.raiseException = raiseException

    def enqueue(self, iterable):
        for item in iterable:
            self.add(item)

    def add(self, item):
        self.queue.put(item)

    def worker(self):
        while not self.queue.empty():
            func = self.queue.get()
            try:
                if func:
                    ret = func()
                    self.results.append(ret) if not isinstance(ret, list) else self.results.extend(ret)
            except Exception as e:
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
            logging.error("Error occured: %s", self.exception)
            if self.raiseException:
                raise self.exception
        return self.results
