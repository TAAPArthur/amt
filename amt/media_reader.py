import importlib
import inspect
import json
import logging
import os
import pickle
import pkgutil
import random

import requests
from requests.adapters import HTTPAdapter

from . import servers, trackers
from .server import ANIME, MANGA, NOT_ANIME, Server
from .settings import Settings
from .tracker import Tracker

SERVERS = []
TRACKERS = []
for _finder, name, _ispkg in pkgutil.iter_modules(servers.__path__, servers.__name__ + '.'):
    module = importlib.import_module(name)
    for _name, obj in dict(inspect.getmembers(module)).items():
        if inspect.isclass(obj) and issubclass(obj, Server) and obj != Server:
            SERVERS.append(obj)
for _finder, name, _ispkg in pkgutil.iter_modules(trackers.__path__, trackers.__name__ + '.'):
    module = importlib.import_module(name)
    for _name, obj in dict(inspect.getmembers(module)).items():
        if inspect.isclass(obj) and issubclass(obj, Tracker) and obj != Tracker:
            TRACKERS.append(obj)


def get_children(abs_path):
    return "'{}'/*".format(abs_path)


class MangaReader:

    cookie_hash = None
    state_hash = None
    trackers = {}
    _servers = {}
    _trackers = []

    def __init__(self, server_list=SERVERS, tracker_list=TRACKERS, settings=None):
        self.settings = settings if settings else Settings()
        self.state = {"media": {}, "bundles": {}, "trackers": {}}
        _servers = {}
        _trackers = []

        self.session = requests.Session()
        if self.settings.max_retires:
            self.session.mount('http://', HTTPAdapter(max_retries=self.settings.max_retires))
            self.session.mount('https://', HTTPAdapter(max_retries=self.settings.max_retires))
        self.load_session_cookies()

        self.session.headers.update({
            "Accept": "text/html,application/xhtml+xml,application/xml;q=1.0,image/webp,image/apng,*/*;q=1.0",
            "Accept-Language": "en,en-US;q=0.9",
            "Connection": "keep-alive",
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/11.0"
        })

        self.load_state()
        assert len(tracker_list) <= 2

        for cls in server_list:
            if cls.id:
                instance = cls(self.session, self.settings)
                self._servers[instance.id] = instance
        for cls in tracker_list:
            if cls.id:
                instance = cls(self.session, self.settings)
                self._trackers.append(instance)

    def get_primary_tracker(self):
        return self._trackers[0]

    def get_secondary_trackers(self):
        return self._trackers[1:]

    def _set_session_hash(self):
        """
        Sets saved cookie_hash
        @return True iff the hash is different than the already saved one

        """
        cookie_hash = hash(str(self.session.cookies))
        if cookie_hash != self.cookie_hash:
            self.cookie_hash = cookie_hash
            return True
        return False

    def load_session_cookies(self):
        """ Load session from disk """
        if self.settings.no_save_session:
            return False

        file_path = os.path.join(self.settings.cache_dir, 'cookies.pickle')
        try:
            with open(file_path, 'rb') as f:
                self.session.cookies = pickle.load(f)
                self._set_session_hash()
                return True
        except FileNotFoundError:
            return False

    def save_session_cookies(self, force=False):
        """ Save session to disk """
        if self.settings.no_save_session or not self._set_session_hash():
            return False

        file_path = os.path.join(self.settings.cache_dir, 'cookies.pickle')
        with open(file_path, 'wb') as f:
            pickle.dump(self.session.cookies, f)
        return True

    def _set_state_hash(self, json_str=None):
        """
        Sets saved sate_hash
        @return True iff the hash is different than the already saved one

        """

        if not json_str:
            json_str = json.dumps(self.state, indent=4, sort_keys=True)
        state_hash = hash(json_str)
        if state_hash != self.state_hash:
            self.state_hash = state_hash
            return True
        return False

    def load_state(self):
        try:
            with open(self.settings.get_metadata(), 'r') as jsonFile:
                self.state = json.load(jsonFile)
                self._set_state_hash()
        except FileNotFoundError:
            self.settings.init()

        self.media = self.state["media"]
        self.bundles = self.state["bundles"]
        self.trackers = self.state["trackers"]

    def save_state(self):
        json_str = json.dumps(self.state)
        if not self._set_state_hash(json_str):
            return False
        with open(self.settings.get_metadata(), 'w') as jsonFile:
            jsonFile.write(json_str)
        return True

    # def sync_with_disk(self):
    # TODO detect files added

    def _get_global_id(self, media_data):
        return str(media_data["server_id"]) + ":" + str(media_data["id"])

    def add_media(self, media_data, no_update=False):
        global_id = self._get_global_id(media_data)
        if global_id in self.media:
            raise ValueError("{} {} is already known".format(global_id, media_data["name"]))

        logging.debug("Adding %s", global_id)
        self.media[global_id] = media_data
        return [] if no_update else self.update_media(media_data)

    def remove_media(self, media_data=None, id=None):
        if id:
            del self.media[id]
        else:
            del self.media[self._get_global_id(media_data)]

    def get_servers(self):
        return self._servers.values()

    def get_servers_ids(self):
        return self._servers.keys()

    def get_server(self, id):
        return self._servers[id]

    def get_media_in_library(self):
        return self.media.values()

    def get_media_ids_in_library(self):
        return self.media.keys()

    def search_for_media(self, term, media_type=None, exact=False):
        result = []
        for server in filter(lambda x: media_type is None or media_type & x.media_type, self.get_servers()):
            result += server.search(term)
        if exact:
            result = list(filter(lambda x: x["name"] == term, result))
        return result

    def mark_chapters_until_n_as_read(self, media_data, N):
        """Marks all chapters whose numerical index <=N as read"""
        for chapter in media_data["chapters"].values():
            chapter["read"] = chapter["number"] <= N

    def get_last_chapter_number(self, media_data):
        return max(media_data["chapters"].values(), key=lambda x: x["number"])["number"]

    def get_last_read(self, media_data):
        return max(filter(lambda x: x["read"], media_data["chapters"].values()), key=lambda x: x["number"], default={"number": -1})["number"]

    def mark_up_to_date(self, server_id=None, N=0, force=False):
        for media_data in self.get_media_in_library():
            if not server_id or media_data["server_id"] == server_id:
                last_read = self.get_last_chapter_number(media_data) - N
                if not force:
                    last_read = max(self.get_last_read(media_data), last_read)
                self.mark_chapters_until_n_as_read(media_data, last_read)

    def download_unread_chapters(self):
        """Downloads all chapters that are not read"""
        return sum([self.download_chapters(media_data) for media_data in self.get_media_in_library()])

    def download_chapters_by_id(self, media_id, num=0):
        self.download_chapters(self.media[media_id], num=num)

    def download_chapters(self, media_data, num=0):
        last_read = self.get_last_read(media_data)
        server = self.get_server(media_data["server_id"])
        counter = 0
        for chapter in sorted(media_data["chapters"].values(), key=lambda x: x["number"]):
            if not chapter["read"] and chapter["number"] > last_read and server.download_chapter(media_data, chapter):
                counter += 1
                if counter == num:
                    break
        return counter

    def _create_bundle_data_entry(self, media_data, chapter_data):
        return dict(media_id=self._get_global_id(media_data), chapter_id=chapter_data["id"], media_name=media_data["name"], chapter_num=chapter_data["number"])

    def _get_unreads(self, media_type, name=None, shuffle=False):
        media = self.get_media_in_library()
        if shuffle:
            media = list(media)
            random.shuffle(media)
        for media_data in media:
            if name is not None and name not in (media_data["server_id"], media_data["name"], self._get_global_id(media_data)):
                continue
            if media_data["media_type"] & media_type == 0:
                continue

            server = self.get_server(media_data["server_id"])
            for chapter in sorted(media_data["chapters"].values(), key=lambda x: x["number"]):
                if not chapter["read"]:
                    yield server, media_data, chapter

    def bundle_unread_chapters(self, name=None, shuffle=False):
        unreads = []
        paths = []
        bundle_data = []
        for server, media_data, chapter in self._get_unreads(MANGA, name=name, shuffle=shuffle):
            dir_path = server.get_dir(media_data, chapter)
            if Server.is_fully_downloaded(dir_path):
                paths.append(get_children(dir_path))
                bundle_data.append(self._create_bundle_data_entry(media_data, chapter))
        if not paths:
            return None

        logging.info("Bundling %s", paths)
        name = self.settings.bundle(" ".join(paths))
        self.bundles[name] = bundle_data
        return name

    def read_bundle(self, name):
        bundle_name = os.path.join(self.settings.bundle_dir, name)
        if self.settings.view(bundle_name):
            self.mark_bundle_as_read(bundle_name)
            return True
        return False

    def mark_bundle_as_read(self, bundle_name, remove=False):
        bundled_data = self.bundles[bundle_name]
        for bundle in bundled_data:
            self.media[bundle["media_id"]]["chapters"][bundle["chapter_id"]]["read"] = True

    def play(self, name=None, shuffle=False, cont=False):
        def get_urls():
            for server, media_data, chapter in self._get_unreads(ANIME, name=name, shuffle=shuffle):
                dir_path = server.get_dir(media_data, chapter)
                if server.is_fully_downloaded(dir_path):
                    pass
                else:
                    yield server.get_stream_url(media_data, chapter), chapter

        for url, chapter in get_urls():
            if self.settings.view(url):
                chapter["read"] = True
                if not cont:
                    break
            else:
                return False
        return True

    def update(self, download=False, media_type_to_download=MANGA):
        logging.info("Updating: download %s", download)
        new_chapters = []
        for media_data in self.get_media_in_library():
            new_chapters += self.update_media(media_data, download, media_type_to_download=media_type_to_download)
        return new_chapters

    def update_media(self, media_data, download=False, media_type_to_download=MANGA, limit=None, page_limit=None):
        """
        Return set of updated chapters or a False-like value
        """
        server = self.get_server(media_data["server_id"])

        def get_chapter_ids(chapters):
            return {x for x in chapters if not chapters[x]["premium"]} if self.settings.free_only else set(chapters.keys())

        chapter_ids = get_chapter_ids(media_data["chapters"])

        server.update_media_data(media_data)

        current_chapter_ids = get_chapter_ids(media_data["chapters"])
        new_chapter_ids = current_chapter_ids - chapter_ids

        new_chapters = sorted([media_data["chapters"][x] for x in new_chapter_ids], key=lambda x: x["number"])
        assert len(new_chapter_ids) == len(new_chapters)
        if download and (media_type_to_download is None or media_type_to_download & media_data["media_type"]):
            for chapter_data in new_chapters[:limit]:
                server.download_chapter(media_data, chapter_data, page_limit)
        return new_chapters

    def is_added(self, tracker_id, tracking_id):
        for media_id in self.get_media_ids_in_library():
            tacker_info = self.get_tracker_info(media_id, tracker_id)
            if tacker_info and tacker_info[0] == tracking_id:
                return self.media[media_id]
        return False

    def get_tracker_info(self, media_id, tracker_id):
        return self.trackers.get(media_id, {}).get(tracker_id, None)

    def track(self, tracker_id, media_id, tracking_id, tracker_title=None):
        if media_id not in self.trackers:
            self.trackers[media_id] = {}

        self.trackers[media_id][tracker_id] = (tracking_id, tracker_title)

    def sync_progress(self, force=False):
        data = []
        tracker = self.get_primary_tracker()
        for media_id, media_data in self.media.items():
            tracker_info = self.get_tracker_info(media_id=media_id, tracker_id=self.get_primary_tracker().id)
            if tracker_info and (force or media_data["progress"] < self.get_last_read(media_data)):
                data.append((tracker_info[0], self.get_last_read(media_data)))
                logging.info("Preparing to update %s", media_data["name"])

        tracker.update(data)

        for media_data in self.get_media_in_library():
            media_data["progress"] = self.get_last_read(media_data)
            self.save_state()
