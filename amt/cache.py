import json
import logging
import os
import re
import time


class Cache():
    def __init__(self, cache_dir):
        self.cache_dir = cache_dir
        self.files = set(os.listdir(self.cache_dir))

    def get(self, url, func):
        key = re.sub(r"[\W]", "", url)
        file_path = os.path.join(self.cache_dir, key)
        if key in self.files and time.time() - os.stat(file_path).st_mtime < 3600 * 24:
            logging.info("Opening cache file %s for %s", file_path, url)
            with open(file_path, "r") as f:
                data = json.load(f)
                if data["key"] == url:
                    return FakeRequestWrapper(data["value"])

        logging.info("Cache miss %s %s", url, key)
        value = func()
        with open(file_path, "w") as f:
            json.dump({"key": url, "value": value.text}, f)

        self.files.add(key)
        return value


class FakeRequestWrapper:
    def __init__(self, text):
        self.text = text

    def json(self):
        return json.loads(self.text)
