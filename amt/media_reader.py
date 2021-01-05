import importlib
import inspect
import json
import logging
import os
import pickle
import pkgutil
import random
from collections import deque
from http.cookiejar import MozillaCookieJar

import requests
from requests.adapters import HTTPAdapter
from urllib3 import Retry

from . import cookie_manager, servers, trackers
from .job import Job
from .server import ALL_MEDIA, ANIME, MANGA, NOT_ANIME, Server
from .settings import Settings
from .tracker import Tracker

SERVERS = set()
TRACKERS = set()


def import_sub_classes(m, base_class, results):
    for _finder, name, _ispkg in pkgutil.iter_modules(m.__path__, m.__name__ + '.'):
        module = importlib.import_module(name)
        for _name, obj in dict(inspect.getmembers(module, inspect.isclass)).items():
            if issubclass(obj, base_class) and obj.id:
                results.add(obj)


import_sub_classes(servers, Server, SERVERS)
import_sub_classes(trackers, Tracker, TRACKERS)


class MangaReader:

    cookie_hash = None
    state_hash = None
    trackers = {}
    _servers = {}
    _trackers = []

    def __init__(self, server_list=SERVERS, tracker_list=TRACKERS, settings=None):
        self.settings = settings if settings else Settings()
        self.state = {"media": {}, "bundles": {}, "trackers": {}, "disabled_media": {}}
        self._servers = {}
        self._trackers = []

        self.session = requests.Session()
        if self.settings.max_retires:
            for prefix in ('http://', 'https://'):
                self.session.mount(prefix, HTTPAdapter(max_retries=Retry(total=self.settings.max_retires, status_forcelist=self.settings.status_to_retry)))

        self.session.headers.update({
            "Accept": "text/html,application/xhtml+xml,application/xml;q=1.0,image/webp,image/apng,*/*;q=1.0",
            "Accept-Language": "en,en-US;q=0.9",
            "Connection": "keep-alive",
            "User-Agent": self.settings.user_agent
        })

        for cls in server_list:
            if cls.id:
                instance = cls(self.session, self.settings)
                self._servers[instance.id] = instance
        for cls in tracker_list:
            if cls.id:
                instance = cls(self.session, self.settings)
                self._trackers.append(instance)
        self.load_session_cookies()
        self.load_state()

    def get_primary_tracker(self):
        return self._trackers[0]

    def get_secondary_trackers(self):
        return self._trackers[1:]

    def get_trackers(self):
        return self._trackers

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

        if self.settings.no_load_session:
            return

        for path in self.settings.get_cookie_files():
            try:
                with open(path, 'r') as f:
                    cookie_manager.load_cookies(f, self.session)
            except FileNotFoundError:
                pass
        self._set_session_hash()

    def save_session_cookies(self, force=False):
        """ Save session to disk """
        if self.settings.no_save_session or not self._set_session_hash():
            return False

        with open(self.settings.get_cookie_file(), 'w') as f:
            for cookie in self.session.cookies:
                l = [cookie.domain, str(cookie.domain_specified), cookie.path, str(cookie.secure).upper(), str(cookie.expires) if cookie.expires else "", cookie.name, cookie.value]
                f.write("\t".join(l) + "\n")
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
            pass

        self.media = self.state["media"]
        self.bundles = self.state["bundles"]
        self.trackers = self.state["trackers"]

        for key in list(self.state["media"].keys()):
            if self.state["media"][key]["server_id"] not in self._servers:
                self.state["disabled_media"][key] = self.state["media"][key]
                del self.state["media"][key]

        for key in list(self.state["disabled_media"].keys()):
            if self.state["disabled_media"][key]["server_id"] in self._servers:
                self.state["media"]["key"] = self.state["disabled_media"][key]
                del self.state["disabled_media"][key]

        for key, value in list(self.state["media"].items()):
            if key != self._get_global_id(value):
                del self.media[key]
                self.media[self._get_global_id(value)] = value

    def save_state(self):
        json_str = json.dumps(self.state, indent=4, sort_keys=True)
        if not self._set_state_hash(json_str):
            return False
        logging.info("Persisting state")
        with open(self.settings.get_metadata(), 'w') as jsonFile:
            jsonFile.write(json_str)
        return True

    # def sync_with_disk(self):
    # TODO detect files added

    def _get_global_id(self, media_data):
        return "{}:{}{}".format(media_data["server_id"], media_data["id"], (media_data["season_id"] if media_data["season_id"] else ""))

    def add_media(self, media_data, no_update=False):
        global_id = self._get_global_id(media_data)
        if global_id in self.media:
            raise ValueError("{} {} is already known".format(global_id, media_data["name"]))

        logging.debug("Adding %s", global_id)
        self.media[global_id] = media_data
        return [] if no_update else self.update_media(media_data)

    def remove_media(self, media_data=None, id=None):
        if id:
            media_data = self._get_single_media(name=id)
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

    def _get_media(self, media_type=ALL_MEDIA, name=None, shuffle=False):
        media = self.get_media_in_library()
        if shuffle:
            media = list(media)
            random.shuffle(media)
        for media_data in media:
            if name is not None and name not in (media_data["server_id"], media_data["name"], self._get_global_id(media_data)):
                continue
            if media_type and media_data["media_type"] & media_type == 0:
                continue
            yield media_data

    def _get_single_media(self, media_type=ALL_MEDIA, name=None):
        return next(self._get_media(media_type=media_type, name=name))

    def _get_unreads(self, media_type, name=None, shuffle=False):

        for media_data in self._get_media(media_type, name, shuffle):
            server = self.get_server(media_data["server_id"])
            for chapter in sorted(media_data["chapters"].values(), key=lambda x: x["number"]):
                if not chapter["read"]:
                    yield server, media_data, chapter

    def for_each(self, func, media_list):
        return Job(self.settings.threads, [lambda x=media_data: func(x) for media_data in media_list]).run()

    def search_for_media(self, term, server_id=None, media_type=None, exact=False):
        def func(x): return x.search(term)
        if server_id:
            results = func(self.get_server(server_id))
        else:
            results = self.for_each(func, filter(lambda x: media_type is None or media_type & x.media_type, self.get_servers()))
        if exact:
            results = list(filter(lambda x: x["name"] == term, results))
        return results

    def mark_chapters_until_n_as_read(self, media_data, N, force=False):
        """Marks all chapters whose numerical index <=N as read"""
        for chapter in media_data["chapters"].values():
            if chapter["number"] <= N:
                chapter["read"] = True
            elif force:
                chapter["read"] = False

    def get_last_chapter_number(self, media_data):
        return max(media_data["chapters"].values(), key=lambda x: x["number"])["number"] if media_data["chapters"] else 0

    def get_last_read(self, media_data):
        return max(filter(lambda x: x["read"], media_data["chapters"].values()), key=lambda x: x["number"], default={"number": -1})["number"]

    def offset(self, name, offset):
        for media_data in self._get_media(name=name):
            media_data["offset"] = offset

    def mark_up_to_date(self, name=None, media_type=None, N=0, force=False, abs=False):
        for media_data in self._get_media(media_type=media_type, name=name):
            last_read = self.get_last_chapter_number(media_data) + N if not abs else N
            if not force:
                last_read = max(self.get_last_read(media_data), last_read)
            self.mark_chapters_until_n_as_read(media_data, last_read, force=force)

    def download_unread_chapters(self, name=None, media_type=None, limit=0):
        """Downloads all chapters that are not read"""
        def func(media_data): return self.download_chapters(media_data, limit)
        return sum(self.for_each(func, map(lambda x: x[1], self._get_unreads(media_type, name=name))))

    def _get_sorted_chapters(self, media_data):
        return sorted(media_data["chapters"].values(), key=lambda x: x["number"])

    def download_specific_chapters(self, name=None, media_data=None, start=0, end=0):
        media_data = self._get_single_media(name=name)
        server = self.get_server(media_data["server_id"])
        for chapter in self.get_chapters_in_range(media_data, start=start, end=end):
            server.download_chapter(media_data, chapter)

    def get_chapters_in_range(self, media_data, start=0, end=0):
        if not end:
            end = start
        for chapter in self._get_sorted_chapters(media_data):
            if start <= chapter["number"] and (end <= 0 or chapter["number"] <= end):
                yield chapter
                if end == start:
                    break

    def download_chapters(self, media_data, limit=0):
        last_read = self.get_last_read(media_data)
        server = self.get_server(media_data["server_id"])
        counter = 0
        for chapter in sorted(media_data["chapters"].values(), key=lambda x: x["number"]):
            if not chapter["read"] and chapter["number"] > last_read and server.download_chapter(media_data, chapter):
                counter += 1
                if counter == limit:
                    break
        return counter

    def _create_bundle_data_entry(self, media_data, chapter_data):
        return dict(media_id=self._get_global_id(media_data), chapter_id=chapter_data["id"], media_name=media_data["name"], chapter_num=chapter_data["number"])

    def bundle_unread_chapters(self, name=None, shuffle=False):
        unreads = []
        paths = []
        bundle_data = []

        def func(x):
            server, media_data, chapter = x
            server.download_chapter(media_data, chapter)
        self.for_each(func, self._get_unreads(MANGA, name=name, shuffle=shuffle))

        for server, media_data, chapter in self._get_unreads(MANGA, name=name, shuffle=shuffle):
            if server.is_fully_downloaded(media_data, chapter):
                paths.append(server.get_children(media_data, chapter))
                bundle_data.append(self._create_bundle_data_entry(media_data, chapter))
        if not paths:
            return None

        logging.info("Bundling %s", paths)
        name = self.settings.bundle(paths)
        self.bundles[name] = bundle_data
        return name

    def read_bundle(self, name):

        bundle_name = os.path.join(self.settings.bundle_dir, name) if name else max(self.bundles.keys())
        if self.settings.open_manga_viewer(bundle_name):
            self.mark_bundle_as_read(bundle_name)
            return True
        return False

    def mark_bundle_as_read(self, bundle_name, remove=False):
        bundled_data = self.bundles[bundle_name]
        for bundle in bundled_data:
            self.media[bundle["media_id"]]["chapters"][bundle["chapter_id"]]["read"] = True

    def stream(self, url, cont=True, download=False):
        for server in self.get_servers():
            if server.can_stream_url(url):
                known = server.is_url_for_known_media(url, {media["id"]: media for media in self.get_media_in_library() if media["server_id"] == server.id})
                if not known:
                    media_data = server.get_media_data_from_url(url)
                    known = server.is_url_for_known_media(url, {media_data["id"]: media_data})
                media_data, chapter = known
                streamable_url = server.get_stream_url(media_data, chapter)
                logging.info("Streaming %s", streamable_url)
                dir_path = server._get_dir(media_data, chapter)

                if download:
                    server.download_chapter(media_data, chapter)
                else:
                    if not server.is_fully_downloaded(media_data, chapter):
                        server.pre_download(media_data, chapter, dir_path=dir_path)
                    if self.settings.open_anime_viewer(streamable_url, server.get_media_title(media_data, chapter), wd=dir_path):
                        chapter["read"] = True
                        if cont:
                            self.play(name=self._get_global_id(known[0]), cont=cont)
        logging.error("Could not find any matching server")

    def get_stream_url(self, name=None, shuffle=False, raw=False):
        for server, media_data, chapter in self._get_unreads(ANIME, name=name, shuffle=shuffle):
            print(server.get_stream_url(media_data, chapter, raw=raw))

    def get_chapters(self, media_type, name, num_list):
        media_data = self._get_single_media(media_type=media_type, name=name)

        server = self.get_server(media_data["server_id"])
        for chapter in self._get_sorted_chapters(media_data):
            if chapter["number"] in num_list:
                yield server, media_data, chapter

    def play(self, name=None, shuffle=False, cont=False, num_list=None):

        for server, media_data, chapter in (self.get_chapters(ANIME, name, num_list) if num_list else self._get_unreads(ANIME, name=name, shuffle=shuffle)):
            dir_path = server._get_dir(media_data, chapter)
            if not server.is_fully_downloaded(media_data, chapter):
                server.pre_download(media_data, chapter, dir_path=dir_path)
            success = self.settings.open_anime_viewer(
                server.get_children(media_data, chapter)if server.is_fully_downloaded(media_data, chapter) else server.get_stream_url(media_data, chapter),
                title=server.get_media_title(media_data, chapter), wd=dir_path)
            if success:
                chapter["read"] = True
                if not cont:
                    break
            else:
                return False
        return True

    def update(self, download=False, media_type_to_download=MANGA):
        logging.info("Updating: download %s", download)
        def func(x): return self.update_media(x, download, media_type_to_download=media_type_to_download)
        return self.for_each(func, self.get_media_in_library())

    def update_media(self, media_data, download=False, media_type_to_download=MANGA, limit=None, page_limit=None):
        """
        Return set of updated chapters or a False-like value
        """
        server = self.get_server(media_data["server_id"])

        def get_chapter_ids(chapters):
            return {x for x in chapters if not chapters[x]["premium"]} if self.settings.free_only else set(chapters.keys())

        chapter_ids = get_chapter_ids(media_data["chapters"])

        server.update_media_data(media_data)
        assert media_data["chapters"]

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

    def sync_progress(self, force=False, media_type=None, dry_run=False):
        data = []
        tracker = self.get_primary_tracker()
        for media_id, media_data in self.media.items():
            if not media_type or media_data["media_type"] == media_type:
                tracker_info = self.get_tracker_info(media_id=media_id, tracker_id=self.get_primary_tracker().id)
                if tracker_info and (force or media_data["progress"] < self.get_last_read(media_data)):
                    data.append((tracker_info[0], self.get_last_read(media_data)))
                    media_data["progress"] = self.get_last_read(media_data)
                    logging.info("Preparing to update %s to %d", media_data["name"], media_data["progress"])

        if data and not dry_run:
            tracker.update(data)
        return True if data else False
