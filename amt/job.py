from queue import Queue
from threading import Thread


class Job:
    def __init__(self, numThreads, iterable=[]):
        self.numThreads = numThreads
        self.enqueue(iterable)
        self.queue = Queue()
        self.exception = None

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
                    func()
            except Exception as e:
                self.exception = e
                raise
            finally:
                self.queue.task_done()

    def run(self):
        if self.numThreads:
            for i in range(self.numThreads):
                Thread(target=self.worker, daemon=True).start()
            self.queue.join()
            if self.exception:
                raise self.exception
        else:
            self.worker()
