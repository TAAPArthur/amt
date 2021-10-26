import importlib
import inspect
import logging
import os
import pkgutil
import random
import re
import shutil

import requests
from requests.adapters import HTTPAdapter
from urllib3 import Retry

from . import servers, trackers
from .job import Job
from .server import Server, TorrentHelper, Tracker
from .servers.local import get_local_server_id
from .settings import Settings
from .state import State
from .util.media_type import MediaType
from .util.name_parser import get_media_name_from_file

SERVERS = set()
TRACKERS = set()
TORRENT_HELPERS = set()


def import_sub_classes(m, base_class, results):
    for _finder, name, _ispkg in pkgutil.iter_modules(m.__path__, m.__name__ + "."):
        try:
            module = importlib.import_module(name)
            for _name, obj in dict(inspect.getmembers(module, inspect.isclass)).items():
                if issubclass(obj, base_class) and obj.id:
                    results.add(obj)
        except ImportError:
            logging.debug("Could not import %s", name)
            pass


import_sub_classes(servers, Server, SERVERS)
import_sub_classes(trackers, Tracker, TRACKERS)
import_sub_classes(servers, TorrentHelper, TORRENT_HELPERS)


class MediaReader:

    def __init__(self, settings=None, server_list=SERVERS, tracker_list=TRACKERS, torrent_helpers_list=TORRENT_HELPERS):
        self.settings = settings if settings else Settings()
        self.session = requests.Session()
        self.state = State(self.settings, self.session)
        self._servers = {}
        self._torrent_helpers = {}
        self._trackers = {}
        self.tracker = None

        if self.settings.max_retries:
            for prefix in ("http://", "https://"):
                self.session.mount(prefix, HTTPAdapter(max_retries=Retry(total=self.settings.max_retries, status_forcelist=self.settings.status_to_retry)))

        self.session.headers.update({
            "Connection": "keep-alive",
            "User-Agent": self.settings.user_agent
        })

        for cls_list, instance_map in ((server_list, self._servers), (tracker_list, self._trackers), (torrent_helpers_list, self._torrent_helpers)):
            for cls in cls_list:
                for instance in cls.get_instances(self.session, self.settings):
                    if self.settings.is_server_enabled(instance.id, instance.official):
                        assert instance.id not in instance_map, f"Duplicate server id: {instance.id}"
                        instance_map[instance.id] = instance

        if self._trackers:
            self.set_tracker(self._trackers.get(self.settings.tracker_id, list(self._trackers.values())[0]))
        self.state.load()
        self.state.configure_media(self._servers)
        self.media = self.state.media
        self.bundles = self.state.bundles

    # Helper methods
    def select_media(self, term, results, prompt, no_print=False, auto_select_if_single=False):  # pragma: no cover
        return results[0] if results else None

    def for_each(self, func, media_list, raiseException=False):
        return Job(self.settings.threads, [lambda x=media_data: func(x) for media_data in media_list], raiseException=raiseException).run()

    def get_servers(self):
        return self._servers.values()

    def get_servers_ids(self):
        return self._servers.keys()

    def get_servers_ids_with_logins(self):
        return [k for k in self._servers.keys() if self.get_server(k).has_login()]

    def get_server(self, id):
        return self._servers.get(id, None)

    def get_torrent_helpers(self):
        return self._torrent_helpers.values()

    def get_media_ids(self):
        return self.media.keys()

    def get_media(self, name=None, media_type=None, tag=None, shuffle=False):
        if isinstance(name, dict):
            yield name
            return
        media = self.media.values()
        if shuffle:
            media = list(media)
            random.shuffle(media)
        for media_data in media:
            if name is not None and name not in (media_data["server_id"], media_data["name"], media_data.global_id):
                continue
            if media_type and media_data["media_type"] & media_type == 0:
                continue
            if tag and tag not in media_data["tags"] or tag == "" and not media_data["tags"]:
                continue
            yield media_data

    def get_single_media(self, name=None, media_type=None):
        return next(self.get_media(media_type=media_type, name=name))

    def get_unreads(self, name=None, media_type=None, shuffle=False, limit=None, any_unread=False):
        count = 0
        for media_data in self.get_media(name, media_type=media_type, shuffle=shuffle):
            server = self.get_server(media_data["server_id"])

            lastRead = media_data.get_last_read()
            for chapter in media_data.get_sorted_chapters():
                if not chapter["read"] and (any_unread or chapter["number"] > lastRead):
                    yield server, media_data, chapter
                    count += not chapter["special"]
                    if limit and count == limit:
                        return

    # Method related to adding/removing media and searching for media

    def add_media(self, media_data, no_update=None):
        global_id = media_data.global_id
        if global_id in self.media:
            raise ValueError("{} {} is already known".format(global_id, media_data["name"]))

        logging.debug("Adding %s", global_id)
        self.media[global_id] = media_data
        os.makedirs(self.settings.get_media_dir(media_data), exist_ok=True)
        if no_update is False or no_update is None and not media_data["chapters"]:
            self.update_media(media_data)

    def search_add(self, term, server_id=None, media_type=None, limit=None, exact=False, servers_to_exclude=[], server_list=None, no_add=False, media_id=None, sort_func=None, raiseException=False):
        def func(x): return x.search(term, limit=limit)
        if server_id:
            results = func(self.get_server(server_id))
        else:
            results = self.for_each(func, filter(lambda x: x.id not in servers_to_exclude and (media_type is None or media_type & x.media_type), server_list if server_list is not None else self.get_servers()), raiseException=raiseException)
        if exact:
            results = list(filter(lambda x: x["name"] == term, results))
        results = list(filter(lambda x: not media_id or str(x["id"]) == str(media_id) or x.global_id == media_id, results))
        if sort_func:
            results.sort(key=sort_func)
        if len(results) == 0:
            return None
        media_data = self.select_media(term, results, "Select media: ", auto_select_if_single=exact or media_id)
        if not no_add and media_data:
            self.add_media(media_data)
        return media_data

    def add_from_url(self, url):
        for server in self.get_servers():
            if server.can_stream_url(url):
                media_data = server.get_media_data_from_url(url)
                if media_data:
                    self.add_media(media_data)
                return media_data
        raise ValueError("Could not find media to add")

    def remove_media(self, media_data=None, id=None):
        if id:
            media_data = self.get_single_media(name=id)
        del self.media[media_data.global_id]

    def auto_import_media(self, files=None, **kwargs):
        for media_type in MediaType:
            path = self.settings.get_external_downloads_dir(media_type, skip_auto_create=True)
            if os.path.exists(path):
                for f in os.listdir(path):
                    torrent_dir = os.path.join(path, f)
                    if os.path.isdir(torrent_dir) and (not files or f in files):
                        self.import_media([torrent_dir], media_type=media_type, **kwargs)

    def import_media(self, files, media_type, link=False, name=None, skip_add=False, fallback_name=None):
        server = self.get_server(get_local_server_id(media_type))
        names = set()
        for file in files:
            logging.info("Trying to import %s (dir: %s)", file, os.path.isdir(file))
            assert file != "/"
            media_name = name

            if os.path.isdir(file):
                media_name = get_media_name_from_file(file, fallback_name, is_dir=True)
                self.import_media(map(lambda x: os.path.join(file, x), os.listdir(file)), media_type, name=media_name, fallback_name=name, link=link, skip_add=skip_add)
                continue
            if not name:
                media_name = get_media_name_from_file(file, fallback_name, is_dir=False)
                logging.info("Detected name %s", media_name)

            assert not os.path.isdir(file)
            dest = server.get_import_media_dest(media_name=media_name, file_name=os.path.basename(file))
            logging.info("Importing to %s", dest)
            if link:
                os.link(file, dest)
            else:
                shutil.move(file, dest)
            names.add(media_name)

        if not skip_add:
            for media_name in names:
                if not any([x["name"] == media_name for x in self.get_media(name=server.id)]):
                    self.search_add(media_name, server_id=server.id, exact=True)

            for media_data in self.get_media(name=server.id):
                self.update_media(media_data)

    ############# Upgrade and migration

    def migrate(self, name, exact=False, move_self=False, force_same_id=False, raw_id=False):
        media_list = []
        last_read_list = []
        failures = 0
        for media_data in list(self.get_media(name=name)):
            self.remove_media(media_data)
            if move_self:
                def func(x): return -sum([media_data.get(key, None) == x[key] for key in x])
                new_media_data = self.search_for_media(media_data["name"], media_type=media_data["media_type"], skip_local_search=True, exact=exact, server_id=media_data["server_id"], media_id=media_data.global_id if raw_id else media_data["id"] if force_same_id else None, sort_func=func)
            else:
                new_media_data = self.search_for_media(media_data["name"], media_type=media_data["media_type"], skip_local_search=True, exact=exact, servers_to_exclude=[media_data["server_id"]])
            if new_media_data:
                media_data.copy_fields_to(new_media_data)
                media_list.append(new_media_data)
                last_read_list.append(media_data.get_last_read())
            else:
                logging.info("Failed to migrate %s", media_data.global_id)
                self.add_media(media_data, no_update=True)
                failures += 1

        self.for_each(self.update_media, media_list, raiseException=True)
        for media_data, last_read in zip(media_list, last_read_list):
            self.mark_chapters_until_n_as_read(media_data, last_read)
        return failures

    def upgrade_state(self):
        if self.state.is_out_of_date():
            if self.state.is_out_of_date_minor():
                for media_data in self.get_media():
                    server = self.get_server(media_data["server_id"])
                    updated_media_data = server.create_media_data(media_data["id"], media_data["name"])
                    for key in updated_media_data.keys():
                        if key not in media_data:
                            media_data[key] = updated_media_data[key]
            else:
                self.migrate(None, move_self=True, force_same_id=True, raw_id=True)
            self.state.update_verion()

    # Updating media

    def update(self, name=None, media_type=None, no_shuffle=False, ignore_errors=False):
        return sum(self.for_each(self.update_media, self.get_media(name=name, media_type=media_type, shuffle=not no_shuffle), raiseException=not ignore_errors))

    def update_media(self, media_data, limit=None, page_limit=None):
        """
        Return number of updated chapters
        """
        server = self.get_server(media_data["server_id"])
        chapter_ids = set(media_data["chapters"].keys())
        server.update_media_data(media_data)

        if not self.settings.get_keep_unavailable(media_data):
            for chapter_id in chapter_ids:
                if chapter_id in media_data["chapters"] and not media_data["chapters"][chapter_id].check_if_updated_and_clear():
                    if not server.is_fully_downloaded(media_data, media_data["chapters"][chapter_id]):
                        del media_data["chapters"][chapter_id]

        return len(media_data["chapters"].keys() - chapter_ids)

    # Downloading

    def download_specific_chapters(self, name=None, media_data=None, start=0, end=0, stream_index=0):
        media_data = self.get_single_media(name=name)
        server = self.get_server(media_data["server_id"])
        if not end:
            end = start
        for chapter in media_data.get_sorted_chapters():
            if start <= chapter["number"] and (end <= 0 or chapter["number"] <= end):
                server.download_chapter(media_data, chapter, stream_index=stream_index)
                if end == start:
                    break

    def download_unread_chapters(self, name=None, media_type=None, limit=0, ignore_errors=False, any_unread=False, page_limit=None, stream_index=0):
        """Downloads all chapters that are not read"""
        def download_selected_chapters(x):
            server, media_data, chapter = x
            return server.download_chapter(media_data, chapter, page_limit=page_limit, stream_index=stream_index)
        return sum(self.for_each(download_selected_chapters, self.get_unreads(name=name, media_type=media_type, any_unread=any_unread, limit=limit), raiseException=not ignore_errors))

    def bundle_unread_chapters(self, name=None, shuffle=False, limit=None, ignore_errors=False):
        paths = []
        bundle_data = []
        self.download_unread_chapters(name=name, media_type=MediaType.MANGA, limit=limit, ignore_errors=ignore_errors)
        for server, media_data, chapter in self.get_unreads(name=name, media_type=MediaType.MANGA, shuffle=shuffle, limit=limit):
            if server.is_fully_downloaded(media_data, chapter):
                paths.append(server.get_children(media_data, chapter))
                bundle_data.append(dict(media_id=media_data.global_id, chapter_id=chapter["id"]))
        if not paths:
            return None

        logging.info("Bundling %s", paths)
        bundle_name = self.settings.bundle(paths, name=name, media_data=self.state.get_lead_media_data(bundle_data))
        self.state.bundles[bundle_name] = bundle_data
        self.state.bundles[""] = bundle_name
        return bundle_name

    def read_bundle(self, name=None):
        bundle_name = name if name else self.state.bundles.get("", max(self.state.bundles.keys()))
        if bundle_name in self.bundles and self.settings.open_bundle_viewer(bundle_name, self.state.get_lead_media_data(bundle_name)):
            self.state.mark_bundle_as_read(bundle_name)
            return True
        return False

    # Viewing chapters and marking read

    def mark_chapters_until_n_as_read(self, media_data, N, force=False):
        """Marks all chapters whose numerical index <=N as read"""
        for chapter in media_data["chapters"].values():
            if chapter["number"] <= N:
                chapter["read"] = True
            elif force:
                chapter["read"] = False

    def mark_read(self, name=None, media_type=None, N=0, force=False, abs=False):
        for media_data in self.get_media(media_type=media_type, name=name):
            last_read = media_data.get_last_chapter_number() + N if not abs else N
            if not force:
                last_read = max(media_data.get_last_read(), last_read)
            self.mark_chapters_until_n_as_read(media_data, last_read, force=force)

    def get_media_by_chapter_id(self, server_id, chapter_id):
        for media in self.get_media():
            if media["server_id"] == server_id:
                if chapter_id in media["chapters"]:
                    return media, media["chapters"][chapter_id]
        return None, None

    def stream(self, url, cont=False, download=False, stream_index=0):
        for server in self.get_servers():
            if server.can_stream_url(url):
                chapter_id = server.get_chapter_id_for_url(url)
                media_data, chapter = self.get_media_by_chapter_id(server.id, chapter_id)
                if not chapter:
                    media_data = server.get_media_data_from_url(url)
                    if not media_data["chapters"]:
                        server.update_media_data(media_data)

                    chapter = media_data["chapters"][chapter_id]
                if download:
                    server.download_chapter(media_data, chapter)
                else:
                    if not server.is_fully_downloaded(media_data, chapter):
                        server.pre_download(media_data, chapter)
                    streamable_url = server.get_stream_url(media_data, chapter, stream_index=stream_index)
                    logging.info("Streaming %s", streamable_url)
                    if self.settings.open_viewer(streamable_url, media_data=media_data, chapter_data=chapter):
                        chapter["read"] = True
                        if cont:
                            return 1 + self.play(name=media_data)
                return 1
        logging.error("Could not find any matching server")
        return False

    def get_stream_url(self, name=None, num_list=None, shuffle=False, limit=None, force_abs=False):
        for server, media_data, chapter in (self.get_chapters(name=name, media_type=MediaType.ANIME, num_list=num_list, force_abs=force_abs) if num_list else self.get_unreads(name=name, media_type=MediaType.ANIME, limit=limit, shuffle=shuffle)):
            for url in server.get_stream_urls(media_data, chapter):
                print(chapter["number"], url)

    def get_chapters(self, media_type, name, num_list, force_abs=False):
        media_data = self.get_single_media(media_type=media_type, name=name)
        last_read = media_data.get_last_read()
        num_list = list(map(lambda x: last_read + x if x <= 0 and not force_abs else x, num_list))
        server = self.get_server(media_data["server_id"])
        for chapter in media_data.get_sorted_chapters():
            if chapter["number"] in num_list:
                yield server, media_data, chapter

    def play(self, name=None, media_type=None, shuffle=False, limit=None, num_list=None, stream_index=0, any_unread=False, force_abs=False):
        num = 0
        for server, media_data, chapter in (self.get_chapters(media_type, name, num_list, force_abs=force_abs) if num_list else self.get_unreads(name=name, media_type=media_type, limit=limit, shuffle=shuffle, any_unread=any_unread)):
            if media_data["media_type"] == MediaType.ANIME:
                if not server.is_fully_downloaded(media_data, chapter):
                    server.pre_download(media_data, chapter)
            else:
                server.download_chapter(media_data, chapter)
            success = self.settings.open_viewer(
                server.get_children(media_data, chapter)if server.is_fully_downloaded(media_data, chapter) else server.get_stream_url(media_data, chapter, stream_index=stream_index),
                media_data=media_data, chapter_data=chapter)
            if success:
                num += 1
                chapter["read"] = True
                if num == limit:
                    break
            else:
                return False
        return num

    # Tacker related functions

    def get_tracker(self):
        return self.tracker

    def get_tracker_by_id(self, tracker_id):
        return self._trackers[tracker_id] if tracker_id else self.get_tracker()

    def get_tracker_ids(self):
        return self._trackers.keys()

    def set_tracker(self, tracker_id):
        self.tracker = self._trackers[tracker_id] if not isinstance(tracker_id, Tracker) else tracker_id

    def get_tracked_media(self, tracker_id, tracking_id):
        media_data_list = []
        for media_data in self.get_media():
            tacker_info = self.get_tracker_info(media_data, tracker_id)
            if tacker_info and tacker_info[0] == tracking_id:
                media_data_list.append(media_data)
        return media_data_list

    def has_tracker_info(self, media_data, tracker_id=None):
        return self.get_tracker_info(media_data, tracker_id=tracker_id) is not None

    def get_tracker_info(self, media_data, tracker_id=None):
        if not tracker_id:
            tracker_id = self.get_tracker().id
        return media_data["trackers"].get(tracker_id, None)

    def track(self, media_data, tracker_id, tracking_id, tracker_title=None):
        media_data["trackers"][tracker_id] = (tracking_id, tracker_title)

    def remove_tracker(self, name, media_type=None, tracker_id=None):
        if not tracker_id:
            tracker_id = self.get_tracker().id
        for media_data in self.get_media(name=name, media_type=media_type):
            del media_data["trackers"][tracker_id]

    def copy_tracker(self, src, dst):
        src_media_data = self.get_single_media(name=src)
        dst_media_data = self.get_single_media(name=dst)
        if self.has_tracker_info(src_media_data):
            tracking_id, tracker_title = self.get_tracker_info(src_media_data)
            self.track(dst_media_data, self.get_tracker().id, tracking_id, tracker_title)

    def sync_progress(self, name=None, media_type=None, force=False, dry_run=False):
        data = []
        media_to_sync = []
        for media_data in self.get_media(name=name, media_type=media_type):
            tracker_info = self.get_tracker_info(media_data=media_data, tracker_id=self.get_tracker().id)
            if tracker_info and (force or media_data["progress"] < int(media_data.get_last_read())):
                data.append((tracker_info[0], media_data.get_last_read(), media_data["progress_volumes"]))
                media_to_sync.append(media_data)
                logging.info("Preparing to update %s from %d to %d", media_data["name"], media_data["progress"], media_data.get_last_read())

        if data and not dry_run:
            self.get_tracker().update(data)
            for media_data in media_to_sync:
                media_data["progress"] = media_data.get_last_read()
        return bool(data)

    def search_for_media(self, name, media_type, exact=False, skip_local_search=False, skip_remote_search=False, **kwargs):
        alt_names = list(filter(lambda x: x, dict.fromkeys([name, name.split(" Season")[0], re.sub(r"\W*$", "", name), re.sub(r"\s*[^\w\d\s]+.*$", "", name), re.sub(r"\W.*$", "", name), get_media_name_from_file(name, is_dir=True)]))) if not exact else [name]
        media_data = known_matching_media = None

        if not skip_local_search:
            for name in alt_names:
                known_matching_media = list(filter(lambda media_data: not self.get_tracker_info(media_data) and
                                                   (not media_type or media_type & media_data["media_type"]) and
                                                   (name.lower() in (media_data["name"].lower(), media_data["season_title"].lower())), self.get_media()))
                if known_matching_media:
                    break

        if known_matching_media:
            logging.debug("Checking among known media")
            media_data = self.select_media(name, known_matching_media, "Select from known media: ")

        elif not skip_remote_search:
            for name in alt_names:
                media_data = self.search_add(name, media_type=media_type, exact=exact, **kwargs)
                if media_data:
                    break
            if not media_data and self.settings.get_download_torrent_cmd(media_type):
                logging.info("Checking to see if %s can be found with helpers", name)
                for name in alt_names:
                    media_data = self.search_add(name, media_type=media_type, exact=exact, server_list=self.get_torrent_helpers(), no_add=True, **kwargs)
                    if media_data:
                        logging.info("Found match; Downloading torrent file")
                        self._torrent_helpers[media_data["server_id"]].download_torrent_file(media_data)
                        logging.info("Starting torrent download")
                        self.settings.start_torrent_download(media_data)
                        return False
        if not media_data:
            logging.info("Could not find media %s", name)
            return False
        return media_data

    def load_from_tracker(self, user_id=None, user_name=None, media_type=None, exact=False, local_only=False, update_progress_only=False, force=False):
        tracker = self.get_tracker()
        data = tracker.get_tracker_list(user_name=user_name) if user_name else tracker.get_tracker_list(id=user_id)
        new_count = 0

        unknown_media = []
        for entry in data:
            if media_type and not entry["media_type"] & media_type:
                logging.debug("Skipping %s", entry)
                continue
            media_data_list = self.get_tracked_media(tracker.id, entry["id"])
            if not media_data_list:
                if update_progress_only:
                    continue
                media_data = self.search_for_media(entry["name"], entry["media_type"], exact=exact, skip_remote_search=local_only)
                if media_data:
                    self.track(media_data, tracker.id, entry["id"], entry["name"])
                    assert self.get_tracked_media(tracker.id, entry["id"])
                    new_count += 1
                else:
                    unknown_media.append(entry["name"])
                    continue
                media_data_list = [media_data]

            for media_data in media_data_list:
                progress = entry["progress"] if not media_data["progress_volumes"] else entry["progress_volumes"]
                self.mark_chapters_until_n_as_read(media_data, progress, force=force)
                media_data["progress"] = progress
        if unknown_media:
            logging.info("Could not find any of %s", unknown_media)
        return new_count
    # MISC

    def offset(self, name, offset):
        for media_data in self.get_media(name=name):
            diff_offset = offset - media_data.get("offset", 0)
            for chapter in media_data["chapters"].values():
                chapter["number"] -= diff_offset
            media_data["offset"] = offset

    def tag(self, name, tag_name):
        for media_data in self.get_media(name=name):
            media_data["tags"].append(tag_name)

    def untag(self, name, tag_name):
        for media_data in self.get_media(name=name):
            if tag_name in media_data["tags"]:
                media_data["tags"].remove(tag_name)

    def clean(self, remove_disabled_servers=False, include_local_servers=False, remove_read=False, remove_not_on_disk=False, bundles=False):
        if remove_not_on_disk:
            for media_data in [x for x in self.get_media() if not os.path.exists(self.settings.get_chapter_metadata_file(x))]:
                logging.info("Removing metadata for %s because it doesn't exist on disk", media_data["name"])
                self.remove_media(media_data)
        media_dirs = {self.settings.get_media_dir(media_data): media_data for media_data in self.get_media()}
        if bundles:
            logging.info("Removing all bundles")
            self.bundles.clear()
            shutil.rmtree(self.settings.bundle_dir)
            os.mkdir(self.settings.bundle_dir)
        for server_dir in os.listdir(self.settings.media_dir):
            server = self.get_server(server_dir)
            server_path = os.path.join(self.settings.media_dir, server_dir)
            if server:
                if include_local_servers or not server.is_local_server():
                    for media_dir in os.listdir(server_path):
                        media_path = os.path.join(server_path, media_dir)
                        if media_path not in media_dirs:
                            logging.info("Removing %s because it has been removed", media_path)
                            shutil.rmtree(media_path)
                            continue
                        media_data = media_dirs[media_path]
                        if remove_read:
                            for chapter_data in media_data.get_sorted_chapters():
                                chapter_path = self.settings.get_chapter_dir(media_data, chapter_data, skip_create=True)
                                if chapter_data["read"] and os.path.exists(chapter_path):
                                    logging.info("Removing %s because it has been read", chapter_path)
                                    shutil.rmtree(chapter_path)

                        chapter_dirs = {self.settings.get_chapter_dir(media_data, chapter_data, skip_create=True): chapter_data for chapter_data in media_data.get_sorted_chapters()}
                        for chapter_dir in os.listdir(media_path):
                            chapter_path = os.path.join(media_path, chapter_dir)
                            if chapter_path not in chapter_dirs and os.path.isdir(chapter_path):
                                logging.info("Removing %s because chapter info has been removed", chapter_path)
                                shutil.rmtree(chapter_path)

            elif remove_disabled_servers:
                logging.info("Removing %s because it is not enabled", server_path)
                shutil.rmtree(server_path)
