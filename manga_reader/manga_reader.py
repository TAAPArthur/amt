from . import servers
from .server import Server
from .settings import Settings
from .trackers.anilist import Anilist

import importlib
import inspect
import json
import logging
import os
import pickle
import pkgutil
import random
import requests
import requests_cache

SERVERS = []
for _finder, name, _ispkg in pkgutil.iter_modules(servers.__path__, servers.__name__ + '.'):
    module = importlib.import_module(name)
    for _name, obj in dict(inspect.getmembers(module)).items():
        if inspect.isclass(obj) and issubclass(obj, Server) and obj != Server:
            SERVERS.append(obj)


class MangaReader:

    def __init__(self, class_list=SERVERS, settings=None, no_load=False):
        self.settings = settings if settings else Settings()
        self._servers = {}
        self.state = {}

        if self.settings.cache:
            logging.debug("Installing cache")
            requests_cache.core.install_cache(expire_after=self.settings.expire_after, allowable_methods=('GET', 'POST'))

        self.session = None
        if not no_load:
            self.load_session()
            self.load_state()
        if not self.session:
            self.session = requests.Session()
        self.session.headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=1.0,image/webp,image/apng,*/*;q=1.0",
            "Accept-Encoding": "gzip, deflate, br",
            "Accept-Language": "en,en-US;q=0.9",
            "Connection": "keep-alive",
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/11.0"
        }

        self.tracker = Anilist(self.session, self.settings.get_secret(Anilist.id))

        for cls in class_list:
            if cls.id:
                instance = cls(self.session, self.settings)
                self._servers[instance.id] = instance

    def get_primary_tracker(self):
        return self.tracker

    def load_session(self):
        """ Load session from disk """
        if self.settings.no_save_session:
            return False

        file_path = os.path.join(self.settings.cache_dir, 'session.pickle')
        try:
            with open(file_path, 'rb') as f:
                self.session = pickle.load(f)
                return True
        except FileNotFoundError:
            pass
        return False

    def save_session(self):
        """ Save session to disk """
        if self.settings.no_save_session:
            return False

        file_path = os.path.join(self.settings.cache_dir, 'session.pickle')
        with open(file_path, 'wb') as f:
            pickle.dump(self.session, f)

    def load_state(self):
        try:
            with open(self.settings.get_metadata(), 'r') as jsonFile:
                self.state = json.load(jsonFile)
        except FileNotFoundError:
            self.settings.init()

    def save_state(self):
        with open(self.settings.get_metadata(), 'w') as jsonFile:
            json.dump(self.state, jsonFile, indent=4)

    # def sync_with_disk(self):
    # TODO detect files added

    def _get_global_id(self, manga_data):
        return str(manga_data["server_id"]) + ":" + str(manga_data["id"])

    def add_manga(self, manga_data, no_update=False):
        self.state[self._get_global_id(manga_data)] = manga_data
        return [] if no_update else self.update_manga(manga_data)

    def remove_manga(self, manga_data=None, id=None):
        if id:
            del self.state[id]
        else:
            del self.state[self._get_global_id(manga_data)]

    def get_servers(self):
        return self._servers.values()

    def get_servers_ids(self):
        return self._servers.keys()

    def get_server(self, id):
        return self._servers[id]

    def is_added(self, tracker_id=None):
        for manga_data in self.get_manga_in_library():
            if manga_data["trackers"][self.get_primary_tracker().id] == tracker_id:
                return manga_data
        return False

    def track(self, manga_data, tracker_id, list_id):
        manga_data["trackers"][self.get_primary_tracker().id] = tracker_id
        manga_data["tracker_lists"][self.get_primary_tracker().id] = list_id

    def get_manga_in_library(self):
        return self.state.values()

    def get_manga_ids_in_library(self):
        return self.state.keys()

    def search_for_manga(self, term, exact=False):
        result = []
        for server in self.get_servers():
            result += server.search(term)
        if exact:
            result = list(filter(lambda x: x["title"] == term, result))
        return result

    def mark_chapters_until_n_as_read(self, manga_data, N):
        """Marks all chapters whose numerical index <=N as read"""
        for chapter in manga_data["chapters"].values():
            if chapter["number"] <= N:
                chapter["read"] = True

    def get_last_chapter_number(self, manga_data):
        return max(manga_data["chapters"].values(), key=lambda x: x["number"])["number"]

    def get_last_read(self, manga_data):
        return max(manga_data["chapters"].values(), key=lambda x: x["number"] if x["read"] else 0)["number"]

    def get_progress(self, manga_data):
        return manga_data["progress"]

    def update_progress(self):
        for manga_data in self.get_manga_in_library():
            manga_data["progress"] = self.get_last_read(manga_data)

    def mark_up_to_date(self, server_id=None, N=0, force=False):
        for manga_data in self.get_manga_in_library():
            if not server_id or manga_data["server_id"] == server_id:
                last_read = self.get_last_chapter_number(manga_data) - N
                if not force:
                    last_read = max(self.get_last_read(manga_data), last_read)
                self.mark_chapters_until_n_as_read(manga_data, last_read)

    def download_unread_chapters(self):
        """Downloads all chapters that are not read"""
        for manga_data in self.state.values():
            for chapter in manga_data["chapters"].values():
                server = self._servers[manga_data["server_id"]]
                if not chapter["read"]:
                    server.download_chapter(manga_data, chapter)

    def download_chapters(self, manga_data, num):
        last_read = self.get_last_read(manga_data)
        chapters = list(manga_data["chapters"].values())
        chapters.sort(key=lambda x: x["number"])
        server = self._servers[manga_data["server_id"]]
        counter = 0
        for chapter in chapters:
            if chapter["number"] > last_read:
                server.download_chapter(manga_data, chapter)
                if counter == num:
                    break

    def compile_unread_chapters(self, shuffle=False):
        unreads = []
        for manga_data in self.state.values():
            unread_dirs = []
            for chapter in manga_data["chapters"].values():
                if not chapter["read"]:
                    dir_path = self.settings.get_chapter_dir(manga_data, chapter)
                    unread_dirs.append("'" + dir_path + "'/*")
            unreads.append(unread_dirs)

        if shuffle:
            random.shuffle(unreads)
        paths = [x for chapters in unreads for x in chapters]
        print(paths)
        logging.info("Bundling %s", paths)
        return self.settings.compile(" ".join(paths))

    def read_bundle(self, bundle_name):
        return self.settings.view(bundle_name)

    def update(self, download=False):
        new_chapters = []
        for manga_data in self.state.values():
            new_chapters += self.update_manga(manga_data, download)
        return new_chapters

    def update_manga(self, manga_data, download=False, limit=None, page_limit=None):
        """
        Return set of updated chapters or a False-like value
        """
        server = self._servers[manga_data["server_id"]]

        def get_chapter_ids(chapters):
            return {x for x in chapters if not chapters[x]["premium"]} if self.settings.free_only else set(chapters.keys())

        chapter_ids = get_chapter_ids(manga_data["chapters"])

        server.update_manga_data(manga_data)

        current_chapter_ids = get_chapter_ids(manga_data["chapters"])
        new_chapter_ids = current_chapter_ids - chapter_ids

        new_chapters = [manga_data["chapters"][x] for x in new_chapter_ids]
        assert len(new_chapter_ids) == len(new_chapters)
        if download:
            for chapter_data in new_chapters[:limit]:
                server.download_chapter(manga_data, chapter_data, page_limit)
        return new_chapters

    def sync_progress(self, force=False):
        with requests_cache.disabled():
            data = []
            tracker = self.get_primary_tracker()
            for manga_data in self.get_manga_in_library():
                if manga_data["tracker_lists"][tracker.id] and (force or manga_data["progress"] < self.get_last_read(manga_data)):
                    data.append((manga_data["tracker_lists"][tracker.id], self.get_last_read(manga_data)))
                    logging.info("Preparing to update %s", manga_data["name"])

            tracker.update(data)
            self.update_progress()
            self.save_state()
