import importlib
import inspect
import logging
import os
import pkgutil
import shutil

from requests import Session

from . import servers, trackers
from .job import Job
from .server import Server, Tracker
from .servers.local import LocalServer
from .settings import Settings
from .state import State
from .util.media_type import MediaType
from .util.name_parser import (find_media_with_similar_name_in_list, get_alt_names)
from .util.progress_type import ProgressType


def import_sub_classes(m, clazz, *args):
    base_classes = [clazz] + list(args)
    result_sets = [set() for i in range(len(base_classes))]
    for _finder, name, _ispkg in pkgutil.iter_modules(m.__path__, m.__name__ + "."):
        try:
            module = importlib.import_module(name)
            for _name, obj in dict(inspect.getmembers(module, inspect.isclass)).items():
                for results, base_class in zip(result_sets, base_classes):
                    if issubclass(obj, base_class) and obj.id:
                        results.add(obj)
        except ImportError as e:
            logging.debug("Could not import %s: %s", name, e)

    return result_sets if args else result_sets[0]


SERVERS = import_sub_classes(servers, Server)
TRACKERS = import_sub_classes(trackers, Tracker)


class MediaReader:

    def __init__(self, state=None, server_list=SERVERS, tracker_list=TRACKERS):
        self.state = state if state else State(Settings())
        self.settings = state.settings
        self.session = Session()
        self._servers = {}
        self._trackers = {}
        self.tracker = None

        for cls_list, instance_map in ((server_list, self._servers), (tracker_list, self._trackers)):
            for cls in cls_list:
                try:
                    for instance in cls.get_instances(self.session, self.settings):
                        if self.settings.is_server_enabled(instance.id, instance.alias, instance.official):
                            assert instance.id not in instance_map, f"Duplicate server id: {instance.id}"
                            instance_map[instance.id] = instance
                except ImportError:
                    logging.debug("Could not instantiate %s", cls)

        self.session.headers.update({
            "Connection": "keep-alive",
            "User-Agent": self.settings.user_agent
        })

        if self._trackers:
            self.set_tracker(self._trackers.get(self.settings.tracker_id, list(self._trackers.values())[0]))
        self.state.set_session(self.session)
        self.state.configure_media(self._servers)
        self.media = self.state.media

    # Helper methods
    def select_media(self, term, results, prompt, no_print=False, auto_select_if_single=False):
        return results[0] if results else None

    def for_each(self, func, media_list, raiseException=False):
        return Job(self.settings.threads, [lambda x=media_data: func(x) for media_data in media_list], raiseException=raiseException).run()

    def get_servers(self):
        return self._servers.values()

    def list_servers(self):
        return sorted(self.state.get_server_ids())

    def get_server(self, id):
        return self._servers.get(id, None)

    def get_media_ids(self):
        return self.media.keys()

    def get_media(self, name=None, **kwargs):
        yield from self.state.get_media(name=name, **kwargs)

    def get_single_media(self, **kwargs):
        return next(self.state.get_media(**kwargs))

    def get_unreads(self, name=None, media_type=None, shuffle=False, limit=None, any_unread=False):
        count = 0
        for media_data in self.get_media(name, media_type=media_type, shuffle=shuffle):
            server = self.get_server(media_data["server_id"])

            lastRead = media_data.get_last_read_chapter_number()
            for chapter in media_data.get_sorted_chapters():
                if not chapter["read"] and (any_unread or (chapter["number"] > lastRead and not chapter["special"])):
                    yield server, media_data, chapter
                    count += 1
                    if limit and count == limit:
                        return

    # Method related to adding/removing media and searching for media

    def list_some_media_from_server(self, server_id, limit=None):
        return self.get_server(server_id).list_media(limit=limit)[:limit]

    def add_media(self, media_data, no_update=None):
        global_id = media_data.global_id
        if global_id in self.media:
            raise ValueError("{} {} is already known".format(global_id, media_data["name"]))

        logging.debug("Adding %s", global_id)
        self.media[global_id] = media_data
        os.makedirs(self.settings.get_media_dir(media_data), exist_ok=True)
        self.state.load_chapter_data(media_data)
        if no_update is False or no_update is None and not media_data["chapters"]:
            self.update_media(media_data)

    def search_add(self, term, server_id=None, media_type=None, limit=None, exact=False, servers_to_exclude=[], server_list=None, no_add=False, media_id=None, raiseException=False):
        def func(x): return x.search(term, literal=exact, limit=limit, media_type=media_type)
        if server_id:
            assert not server_list
            results = func(self.get_server(server_id))
        else:
            results = self.for_each(func, filter(lambda x: x.id not in servers_to_exclude and (media_type is None or media_type & x.media_type), server_list if server_list is not None else self.get_servers()), raiseException=raiseException)

        results.sort(key=lambda x: (x[0], self.settings.get_search_score(x[1])))

        results = map(lambda x: x[1], results)
        if exact:
            results = filter(lambda x: x["name"] == term, results)
        if media_id:
            results = filter(lambda x: str(x["id"]) == str(media_id) or x.global_id == media_id, results)
        results = list(results)[:limit]
        if len(results) == 0:
            return None
        media_data = self.select_media(term, results[:limit], "Select media: ", auto_select_if_single=exact or media_id)
        if media_data:
            self.maybe_resolve_media_type(media_data, media_type_filter=media_type)
            if not no_add:
                self.add_media(media_data)

        return media_data

    def get_related_media_from_tracker_association(self, name, tracker_data, server_id=None):
        media_list = self.for_each(lambda url: self.add_from_url(url, server_id=server_id, skip_add=True, supress_exception=True), tracker_data["external_links"])
        if tracker_data["streaming_links"]:
            media_list.append(self.add_from_url(tracker_data["streaming_links"][0], server_id=server_id, skip_add=True, supress_exception=True))

        media_set = list({media_data.global_id: media_data for media_data in filter(bool, media_list)}.values())
        media_list = []
        for media_data in media_set:
            server = self.get_server(media_data["server_id"])
            media_list.extend(server.get_related_media_seasons(media_data))

        if media_set:
            return self.select_media(name, media_set, "Select from tracker links: ")

    def search_for_media(self, name, media_type=None, exact=False, server_id=None, skip_local_search=False, skip_remote_search=False, tracker_data=None, **kwargs):
        media_data = known_matching_media = None

        if not skip_local_search:
            alt_names = get_alt_names(name) if not exact else [name]
            known_matching_media = list(find_media_with_similar_name_in_list(alt_names, filter(lambda x: not self.get_tracker_info(x), self.get_media(media_type=media_type))))
            if known_matching_media:
                logging.debug("Checking among known media")
                media_data = self.select_media(name, known_matching_media, "Select from known media: ")

        if not media_data and tracker_data:
            media_data = self.get_related_media_from_tracker_association(name, tracker_data, server_id=server_id)
            if media_data:
                if media_data.global_id not in self.get_media_ids():
                    self.add_media(media_data)
                else:
                    media_data = self.media[media_data.global_id]

        if not media_data and not skip_remote_search:
            media_data = self.search_add(name, media_type=media_type, exact=exact, server_id=server_id, **kwargs)
        if not media_data:
            logging.info("Could not find media %s", name)
            return False
        return media_data

    def add_from_url(self, url, skip_add=False, server_id=None, **kwargs):
        for server in self.get_servers():
            if server_id in (None, server.id) and server.can_add_media_from_url(url):
                media_data = server.get_media_data_from_url(url)
                if not skip_add:
                    self.add_media(media_data)
                return media_data
        return False

    def remove_media(self, **kwargs):
        media_data = self.get_single_media(**kwargs)
        del self.media[media_data.global_id]

    def import_media(self, files, media_type, link=False, name=None, skip_add=False, dry_run=False):
        server = self.get_server(LocalServer.id)
        names = set()
        no_errors = True
        for file in files:
            file = os.path.realpath(file)
            logging.info("Trying to import %s (dir: %s)", file, os.path.isdir(file))
            if os.path.isdir(file):
                self.import_media(map(lambda x: os.path.join(file, x), os.listdir(file)), media_type=media_type, link=link, name=name or os.path.basename(file), skip_add=skip_add, dry_run=dry_run)
                continue
            if not name:
                logging.info("Name needs to be specified for %s", file)
                no_errors = False
                continue

            assert not os.path.isdir(file)
            dest = server.get_import_media_dest(media_name=name, file_name=os.path.basename(file))
            logging.info("Importing to %s under media %s", dest, name)
            if not dry_run:
                if link:
                    print("link")
                    os.link(file, dest)
                else:
                    shutil.move(file, dest)
            names.add(name)

        if not skip_add and not dry_run:
            media_list = list(self.get_media(name=server.id))
            for media_name in names:
                for media_data in media_list:
                    if media_data["name"] == media_name:
                        self.update_media(media_data)
                        break
                else:
                    self.search_add(media_name, media_type=media_type, server_id=server.id, exact=True)
        return no_errors

    ############# Upgrade and migration

    def migrate(self, name, media_type=None, exact=False, move_self=False, force_same_id=False, raw_id=False, server_id=None, **kwargs):
        media_list = []
        last_read_list = []
        failures = 0
        for media_data in list(self.get_media(name=name)):
            if move_self:
                new_media_data = self.search_for_media(media_data["name"], media_type=media_data["media_type"], skip_local_search=True, exact=exact, server_id=media_data["server_id"], media_id=media_data.global_id if raw_id else media_data["id"] if force_same_id else None, no_add=True)
            else:
                new_media_data = self.search_for_media(media_data["name"], media_type=media_type or media_data["media_type"], skip_local_search=True, exact=exact, servers_to_exclude=[media_data["server_id"]], no_add=True, **kwargs)
            if new_media_data:
                media_data.copy_fields_to(new_media_data)
                media_list.append(new_media_data)
                last_read_list.append(media_data.get_last_read_chapter_number())
                self.remove_media(name=media_data)
                self.add_media(new_media_data, no_update=True)
            else:
                logging.info("Failed to migrate %s", media_data.global_id)
                failures += 1

        self.for_each(self.update_media, media_list, raiseException=True)
        for media_data, last_read in zip(media_list, last_read_list):
            self.mark_chapters_until_n_as_read(media_data, last_read)
        return failures

    def upgrade_state_if_server_version_changed(self):
        for media_data in self.get_media():
            server = self.get_server(media_data["server_id"])
            if server and media_data.get("version", 0) != server.version:
                self.update(media_data)
                media_data["version"] = server.version

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
        server.update(media_data)

        if not self.settings.get_keep_unavailable(media_data):
            for chapter_id in chapter_ids:
                if chapter_id in media_data["chapters"] and not media_data["chapters"][chapter_id].check_if_updated_and_clear():
                    if not server.is_fully_downloaded(media_data, media_data["chapters"][chapter_id]):
                        read = media_data["chapters"][chapter_id]["read"]
                        number = media_data["chapters"][chapter_id]["number"]
                        del media_data["chapters"][chapter_id]
                        new_chapter_id = media_data.get_chapter_number_to_id(number)
                        if new_chapter_id:
                            media_data["chapters"][new_chapter_id]["read"] = read

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

    def download_unread_chapters(self, name=None, media_type=None, limit=0, ignore_errors=False, any_unread=False, page_limit=None, stream_index=0, force=False):
        """Downloads all chapters that are not read"""

        unique_media = {}
        for server, media_data, chapter in self.get_unreads(name=name, media_type=media_type, any_unread=any_unread, limit=limit):
            if media_data.global_id not in unique_media:
                unique_media[media_data.global_id] = []
            unique_media[media_data.global_id].append((server, media_data, chapter))

        def download_selected_chapters_for_server(x):
            return sum([server.download_chapter(media_data, chapter, page_limit=page_limit, stream_index=stream_index, supress_exeception=force) for server, media_data, chapter in x])
        return sum(self.for_each(download_selected_chapters_for_server, unique_media.values(), raiseException=not ignore_errors))

    def get_remaining_chapters(self, name=None):
        for media_data in self.get_media(name):
            server = self.get_server(media_data["server_id"])
            if not (server.has_chapter_limit() and server.has_login() and server.needs_to_login() and not server.relogin()):
                yield media_data.global_id, *server.get_remaining_chapters(media_data)

    # Viewing chapters and marking read

    def mark_chapters_until_n_as_read(self, media_data, N, force=False):
        """Marks all chapters whose numerical index <=N as read"""
        for chapter in media_data["chapters"].values():
            if chapter["number"] <= N:
                chapter["read"] = True
            elif force:
                chapter["read"] = False

    def mark_read(self, name=None, media_type=None, progress=False, N=0, force=False, abs=False):
        for media_data in self.get_media(media_type=media_type, name=name):
            last_read = media_data.get_last_chapter().get("number", 0) + N if not abs else N
            if progress:
                last_read = media_data["progress"]
            if not force:
                last_read = max(media_data.get_last_read_chapter_number(), last_read)
            self.mark_chapters_until_n_as_read(media_data, last_read, force=force)

    def search_for_chapter_on_different_server(self, ref_media_data, ref_chapter_data):
        def func(x): return x.search(ref_media_data["name"])
        results = self.for_each(func, filter(lambda x: not x.torrent and x.id != ref_media_data["server_id"] and (ref_media_data["media_type"] & x.media_type), self.get_servers()))

        results.sort(key=lambda x: (x[0], self.settings.get_search_score(x[1])))
        results = list(map(lambda x: x[1], results))
        self.for_each(self.update_media, [media_data for media_data in results if not media_data.chapters])

        results = list(filter(lambda x: x[1] is not None, map(lambda media_data: (media_data, media_data["chapters"].get(media_data.get_chapter_number_to_id(ref_chapter_data["number"]))), results)))
        ids = set((ref_media_data["id"], ref_media_data["alt_id"], ref_chapter_data["id"], ref_chapter_data["alt_id"]))
        results.sort(key=lambda x: len(ids.intersection((x[0]["alt_id"], x[0]["id"], x[1]["id"], x[1]["alt_id"],))), reverse=True)
        data = self.select_media(f"{ref_media_data}{ref_chapter_data}", results, "Select chapter: ", auto_select_if_single=True)
        return data

    def stream(self, url, cont=False, media_type=None, download=False, stream_index=0, offset=0, record=False, convert=False):
        for server in self.get_servers():
            if server.can_stream_url(url):
                chapter_id = server.get_chapter_id_for_url(url)
                media_data = server.get_media_data_from_url(url)
                if record and media_data.global_id in self.media:
                    media_data = self.media[media_data.global_id]
                if chapter_id not in media_data["chapters"]:
                    self.update_media(media_data)
                chapter_data = media_data["chapters"][chapter_id]

                self.maybe_resolve_media_type(media_data, media_type)

                if convert:
                    media_data, chapter_data = self.search_for_chapter_on_different_server(media_data, chapter_data)

                if record and media_data.global_id not in self.media:
                    self.add_media(media_data, no_update=True)

                if download:
                    server.download_chapter(media_data, chapter_data)
                else:
                    min_chapter_num = chapter_data["number"] + offset
                    num_list = list(map(lambda x: x["number"], filter(lambda x: x["number"] >= min_chapter_num, media_data["chapters"].values())))
                    return self.play(name=media_data, num_list=num_list, limit=None if cont else 1, force_abs=True) if num_list else False
                return 1
        logging.error("Could not find any matching server")
        return False

    def get_stream_url(self, name=None, num_list=None, shuffle=False, limit=None, force_abs=False):
        for server, media_data, chapter in self.get_chapters(name=name, media_type=MediaType.ANIME, num_list=num_list, force_abs=force_abs, limit=limit, shuffle=shuffle):
            for url in server.get_stream_urls(media_data, chapter):
                yield chapter["number"], url

    def get_chapters(self, name, media_type, num_list, limit=None, shuffle=False, any_unread=False, force_abs=False, null_terminate=False):
        media_data = self.get_single_media(media_type=media_type, name=name)
        last_read = media_data.get_last_read_chapter_number()
        if num_list:
            num_list = list(map(lambda x: last_read + x if x <= 0 and not force_abs else x, num_list))
            server = self.get_server(media_data["server_id"])
            for chapter in media_data.get_sorted_chapters():
                if chapter["number"] in num_list:
                    yield server, media_data, chapter
        else:
            yield from self.get_unreads(name=name, media_type=media_type, limit=limit, shuffle=shuffle, any_unread=any_unread)
        if null_terminate:
            yield None

    def maybe_resolve_media_type(self, media_data, media_type_filter=None):
        if bin(media_data["media_type"]).count('1') != 1:
            types = [media_type for media_type in MediaType if media_type & media_data["media_type"] and (not media_type_filter or media_type & media_type_filter)]
            media_type = self.select_media("Select type", types, prompt=f"What type is {media_data['name']}", auto_select_if_single=True)
            if media_type:
                media_data["media_type"] = media_type.value
                media_data["media_type_name"] = media_type.name

    def play(self, name=None, media_type=None, shuffle=False, limit=None, num_list=None, stream_index=0, any_unread=False, force_abs=False, force=False, force_stream=False, batch_size=1):
        num = 0
        batch = []
        media_chapters = []
        for info in self.get_chapters(name, media_type=media_type, num_list=num_list, limit=limit, shuffle=shuffle, any_unread=any_unread, force_abs=force_abs, null_terminate=True):
            if info:
                server, media_data, chapter = info
                self.maybe_resolve_media_type(media_data, media_type)
                if media_data["media_type"] == MediaType.ANIME:
                    if not server.is_fully_downloaded(media_data, chapter):
                        server.pre_download(media_data, chapter)
                else:
                    server.download_chapter(media_data, chapter, supress_exeception=not force)

                if server.is_fully_downloaded(media_data, chapter) and not force_stream:
                    batch.extend(server.get_children(media_data, chapter))
                else:
                    batch.extend(server.get_stream_url(media_data, chapter, stream_index=stream_index))
                media_chapters.append((media_data, chapter))

                if len(media_chapters) != batch_size:
                    continue
            elif not batch:
                continue

            self.state.save_session_cookies()
            success = self.settings.open_viewer(batch, media_chapters)
            batch = []
            if success:
                num += len(media_chapters)
                for _, chapter in media_chapters:
                    chapter["read"] = True
                media_chapters.clear()
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
            if "nextTimeStampTracker" in media_data:
                del media_data["nextTimeStampTracker"]

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
            last_read_chapter = media_data.get_last_read_chapter()
            if last_read_chapter and (force or media_data["progress"] < last_read_chapter["number"]):
                media_to_sync.append((media_data, last_read_chapter["number"]))
                if tracker_info:
                    if media_data["media_type"] == MediaType.ANIME:
                        data.append((tracker_info[0], last_read_chapter["number"], False))
                    elif media_data["progress_type"] != ProgressType.CHAPTER_VOLUME:
                        data.append((tracker_info[0], last_read_chapter["number"], media_data["progress_type"] == ProgressType.VOLUME_ONLY))
                    else:
                        data.append((tracker_info[0], last_read_chapter["number"], False))
                        data.append((tracker_info[0], last_read_chapter["volume_number"], True))
                    logging.info("Preparing to update %s from %d to %d", media_data["name"], media_data["progress"], last_read_chapter["number"])

        if data and not dry_run:
            self.get_tracker().update(data)
        for media_data, last_chapter_num in media_to_sync:
            media_data["progress"] = last_chapter_num

    def stats_update(self, username=None, user_id=None):
        data = list(self.get_tracker().get_full_list_data(id=user_id, user_name=username))
        self.state.save_stats(username or user_id, data)

    def load_from_tracker(self, user_id=None, user_name=None, media_type=None, exact=False, local_only=False, no_add=False, force=False, remove=False, **kwargs):
        tracker = self.get_tracker()
        data = tracker.get_tracker_list(user_name=user_name) if user_name else tracker.get_tracker_list(id=user_id)
        new_count = 0

        unknown_media = []
        tracked_media = []
        for entry in data:
            if media_type and not entry["media_type"] & media_type:
                logging.debug("Skipping %s", entry)
                continue
            media_data_list = self.get_tracked_media(tracker.id, entry["id"])
            if not media_data_list:
                if no_add:
                    continue
                media_data = self.search_for_media(entry["name"], entry["media_type"], exact=exact, skip_remote_search=local_only, tracker_data=entry, **kwargs)
                if media_data:
                    self.maybe_resolve_media_type(media_data, media_type_filter=media_type)
                    self.track(media_data, tracker.id, entry["id"], entry["name"])
                    assert self.get_tracked_media(tracker.id, entry["id"])
                    new_count += 1
                else:
                    unknown_media.append(entry["name"])
                    continue
                media_data_list = [media_data]

            tracked_media.extend(map(lambda x: x.global_id, media_data_list))
            for media_data in media_data_list:
                progress = entry["progress"] if media_data["progress_type"] != ProgressType.VOLUME_ONLY or entry["progress_volumes"] is None else entry["progress_volumes"]
                self.mark_chapters_until_n_as_read(media_data, progress, force=force)
                media_data["progress"] = progress
                media_data["nextTimeStampTracker"] = entry["nextTimeStamp"]
        if unknown_media:
            logging.info("Could not find any of %s", unknown_media)
        if remove:
            for media_data in list(self.get_media(media_type=media_type)):
                if media_data.global_id not in tracked_media:
                    logging.info("Removing %s because it is no longer present on tracker", media_data.global_id)
                    self.remove_media(name=media_data)
        return new_count

    def login(self, server_ids=None, force=False):
        failures = False
        used_alias = set()
        for server in self.get_servers():
            if server.alias not in used_alias and server.has_login() and (not server_ids or server.id in server_ids or server.alias in server_ids):
                if server.alias:
                    used_alias.add(server.alias)
                if (force or server.needs_to_login()) and not server.relogin():
                    logging.error("Failed to login into %s", server.id)
                    failures = True
        return not failures

    # MISC

    def offset(self, name, offset):
        for media_data in self.get_media(name=name):
            local_offset = offset if offset is not None else media_data.get_first_chapter_number_greater_than_zero() - 1
            diff_offset = local_offset - media_data.get("offset", 0)
            for chapter in media_data["chapters"].values():
                chapter["number"] -= diff_offset
            media_data["offset"] = local_offset

    def tag(self, name, tag_name):
        for media_data in self.get_media(name=name):
            media_data["tags"].append(tag_name)

    def untag(self, name, tag_name):
        for media_data in self.get_media(name=name):
            if tag_name in media_data["tags"]:
                media_data["tags"].remove(tag_name)

    def clean(self, remove_disabled_servers=False, include_local_servers=False, remove_read=False, remove_not_on_disk=False, url_cache=False):
        if remove_not_on_disk:
            for media_data in [x for x in self.get_media() if not os.path.exists(self.settings.get_chapter_metadata_file(x))]:
                logging.info("Removing metadata for %s because it doesn't exist on disk", media_data["name"])
                self.remove_media(name=media_data)
        if url_cache:
            if os.path.exists(self.settings.get_web_cache_dir()):
                shutil.rmtree(self.settings.get_web_cache_dir())
        if not os.path.exists(self.settings.media_dir):
            return
        media_dirs = {self.settings.get_media_dir(media_data): media_data for media_data in self.get_media()}
        for server_dir in os.listdir(self.settings.media_dir):
            server = self.get_server(server_dir)
            server_path = os.path.join(self.settings.media_dir, server_dir)
            if not server:
                if remove_disabled_servers:
                    logging.info("Removing %s because it is not enabled", server_path)
                    shutil.rmtree(server_path)
            elif include_local_servers or not server.is_local_server():
                for media_dir in os.listdir(server_path):
                    media_path = os.path.join(server_path, media_dir)
                    if media_path not in media_dirs:
                        logging.info("Removing %s because it has been removed", media_path)
                        shutil.rmtree(media_path)
                        continue
                    media_data = media_dirs[media_path]
                    for chapter_data in media_data.get_sorted_chapters():
                        chapter_path = self.settings.get_chapter_dir(media_data, chapter_data, skip_create=True)
                        if not os.path.exists(chapter_path):
                            continue
                        if remove_read and chapter_data["read"]:
                            logging.info("Removing %s because it has been read", chapter_path)
                            shutil.rmtree(chapter_path)
                        elif not server.is_fully_downloaded(media_data, chapter_data):
                            logging.info("Removing %s because it hasn't been fully downloaded", chapter_path)
                            shutil.rmtree(chapter_path)

                    chapter_dirs = {self.settings.get_chapter_dir(media_data, chapter_data, skip_create=True): chapter_data for chapter_data in media_data.get_sorted_chapters()}
                    for chapter_dir in os.listdir(media_path):
                        chapter_path = os.path.join(media_path, chapter_dir)
                        if chapter_path not in chapter_dirs and os.path.isdir(chapter_path):
                            logging.info("Removing %s because chapter info has been removed", chapter_path)
                            shutil.rmtree(chapter_path)
