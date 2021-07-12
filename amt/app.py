import logging
import os
import re
import shutil

from . import stats
from .media_reader import MediaReader
from .server import ANIME, MANGA, NOVEL
from .servers.custom import get_local_server_id
from .stats import SortIndex, StatGroup

TYPE_NAMES = {MANGA: "Manga", NOVEL: "Novel", ANIME: "Anime"}


class Application(MediaReader):
    auto_select = False

    def save(self):
        self.save_session_cookies()
        self.state.save()

    def print_results(self, results):
        for i, result in enumerate(results):
            print("{:4}| {}:{}\t{} {} ({})".format(i, result["server_id"], result["id"], result["name"], result["season_title"], TYPE_NAMES[result["media_type"]]))

    def select_media(self, term, results, prompt):
        index = 0

        print("Looking for", term)
        if not self.auto_select and len(results) > 1:
            self.print_results(results)
            index = input(prompt)
        try:
            return results[int(index)]
        except (ValueError, IndexError):
            logging.warning("Invalid input; skipping")
            return None

    def search_add(self, term, server_id=None, media_type=None, exact=False, servers_to_exclude=[], no_add=False):
        results = self.search_for_media(term, server_id=server_id, media_type=media_type, exact=exact, servers_to_exclude=servers_to_exclude)
        if len(results) == 0:
            return None
        media_data = self.select_media(term, results, "Select media: ")
        if not no_add and media_data:
            self.add_media(media_data)
        return media_data

    def select_chapter(self, term, quality=0, **kwargs):
        media_data = self.search_add(term, **kwargs, no_add=True)
        if media_data:
            self.update_media(media_data)
            self.list_chapters(media_data)
            chapter = self.select_media(term, self._get_sorted_chapters(media_data), "Select episode")
            if media_data["media_type"] == ANIME:
                return self.play(name=media_data, num_list=[chapter["number"]], force_abs=True, quality=quality)
            else:
                return self.view_chapters(name=media_data, num_list=[chapter["number"]], force_abs=True)

    def add_from_url(self, url):
        for server in self.get_servers():
            if server.can_stream_url(url):
                media_data = server.get_media_data_from_url(url)
                if media_data:
                    self.add_media(media_data)
                return media_data
        raise ValueError("Could not find media to add")

    def _name_matches_media(self, name, media_data):
        return (name.lower().startswith(media_data["name"].lower()) or
                name.lower().startswith(media_data["season_title"].lower()) or
                name.lower() in (media_data["name"].lower(), media_data["season_title"].lower()))

    def _search_for_tracked_media(self, name, media_type, exact=False, local_only=False):
        alt_names = dict.fromkeys([name, re.sub(r"\W*$", "", name), re.sub(r"[^\w\d\s]+.*$", "", name)])
        media_data = None

        for name in alt_names:
            known_matching_media = list(filter(lambda x: not self.get_tracker_info(x) and
                                               (not media_type or media_type & x["media_type"]) and
                                               (self._name_matches_media(name, x)), self.get_media_in_library()))
            if known_matching_media:
                break

        if known_matching_media:
            logging.debug("Checking among known media")
            media_data = self.select_media(name, known_matching_media, "Select from known media: ")

        elif not local_only:
            for name in alt_names:
                media_data = self.search_add(name, media_type=media_type)
                if media_data:
                    break
        if not media_data:
            logging.info("Could not find media %s", name)
            return False
        return media_data

    def migrate(self, name, move_self=False):
        for media_data in list(self._get_media(name=name)):
            self.remove_media(media_data)
            if move_self:
                new_media_data = self.search_add(media_data["name"], server_id=media_data["server_id"])
            else:
                new_media_data = self.search_add(media_data["name"], media_type=media_data["media_type"], servers_to_exclude=[media_data["server_id"]])
            self.copy_tracker(media_data, new_media_data)
            self.mark_chapters_until_n_as_read(new_media_data, self.get_last_read(media_data))

    def share_tracker(self, name=None, media_type=None, exact=True):
        tracker = self.get_primary_tracker()
        for media_data in self._get_media(name=name, media_type=media_type):
            info = self.get_tracker_info(media_data, tracker.id)
            if info:
                tracking_id, tracker_title = info
                other_media = self._search_for_tracked_media(tracker_title, media_type, local_only=True)
                if other_media:
                    assert media_data != other_media
                    logging.info("Sharing tracker of %s with %s", media_data.global_id, other_media.global_id)
                    self.track(other_media, tracker.id, tracking_id, tracker_title)

    def copy_tracker(self, src, dst):
        src_media_data = self._get_single_media(name=src)
        dst_media_data = self._get_single_media(name=dst)
        tracking_id, tracker_title = self.get_tracker_info(src_media_data, self.get_primary_tracker().id)
        self.track(dst_media_data, self.get_primary_tracker().id, tracking_id, tracker_title)

    def remove_tracker(self, name, media_type=None):
        for media_data in self._get_media(name=name, media_type=media_type):
            self.untrack(media_data)

    def load_from_tracker(self, user_id=None, user_name=None, media_type_filter=None, exact=True, local_only=False, update_progress_only=False, force=False):
        tracker = self.get_primary_tracker()
        data = tracker.get_tracker_list(user_name=user_name) if user_name else tracker.get_tracker_list(id=user_id)
        count = 0
        new_count = 0

        unknown_media = []
        for entry in data:
            media_type = entry["media_type"]
            if media_type_filter and not media_type & media_type_filter:
                logging.debug("Skipping %s", entry)
                continue
            media_data_list = self.get_tracked_media(tracker.id, entry["id"])
            if not media_data_list:
                if update_progress_only:
                    continue
                media_data = self._search_for_tracked_media(entry["name"], media_type, exact=exact, local_only=local_only)
                if media_data:
                    self.track(media_data, tracker.id, entry["id"], entry["name"])
                    assert self.get_tracked_media(tracker.id, entry["id"])
                    new_count += 1
                else:
                    unknown_media.append(entry["name"])
                    continue
                media_data_list = [media_data]

            for media_data in media_data_list:
                progress = entry["progress"] if not media_data["progressVolumes"] else entry["progressVolumes"]
                self.mark_chapters_until_n_as_read(media_data, progress, force=force)
                media_data["progress"] = progress
            count += 1
        if unknown_media:
            logging.info("Could not find any of %s", unknown_media)

        self.list()
        return count, new_count

    def list_servers(self):
        for id in sorted(self.get_servers_ids()):
            print(id)

    def list(self):
        for i, result in enumerate(self.get_media_in_library()):
            last_chapter_num = self.get_last_chapter_number(result)
            last_read = self.get_last_read(result)
            print("{:4}|\t{}\t{} {}\t{}/{}".format(i, result.global_id, result["name"], result["season_title"], last_read, last_chapter_num))

    def list_chapters(self, name):
        media_data = self._get_single_media(name=name)
        for chapter in self._get_sorted_chapters(media_data):
            print("{:4}:{}".format(chapter["number"], chapter["title"]))

    def _get_all_names(self, media_type=None, disallow_servers=False):
        if not disallow_servers:
            for id in self.get_servers_ids():
                if not media_type or self.get_server(id).media_type & media_type:
                    yield id
        for id, media in self.media.items():
            if not media_type or media["media_type"] & media_type:
                yield id
                yield media["name"]

    def get_all_names(self, media_type=None, disallow_servers=False):
        return list(self._get_all_names(media_type, disallow_servers))

    def get_all_single_names(self, media_type=None):
        return self.get_all_names(media_type=media_type, disallow_servers=True)

    def test_login(self, server_ids=None, force=False):
        failures = False
        for server in self.get_servers():
            if server.has_login and (not server_ids or server.id in server_ids):
                if (force or server.needs_to_login()) and not server.relogin():
                    logging.error("Failed to login into %s", server.id)
                    failures = True
        return not failures

    def upgrade_state(self):
        media = self.get_media_in_library()

        def _upgrade_dict(current_dict, new_dict):
            for old_key in current_dict.keys() - new_dict.keys():
                logging.info("Removing old key %s", old_key)
                current_dict.pop(old_key)
            for new_key in new_dict.keys() - current_dict.keys():
                logging.info("Adding new key %s", new_key)
                current_dict[new_key] = new_dict[new_key]

        for media_data in media:
            server = self.get_server(media_data["server_id"])
            new_data = server.create_media_data(media_data["id"], media_data["name"])
            _upgrade_dict(media_data, new_data)
            os.makedirs(self.settings.get_media_dir(media_data), exist_ok=True)
            for chapter_data in media_data["chapters"].values():
                server.update_chapter_data(new_data, chapter_data["id"], chapter_data["title"], chapter_data["number"])
                _upgrade_dict(chapter_data, new_data["chapters"][chapter_data["id"]])

    def import_media(self, files, media_type, link=False, name=None, no_update=False):
        func = shutil.move if not link else os.link

        local_server_id = get_local_server_id(media_type)
        custom_server_dir = self.settings.get_server_dir(local_server_id)
        os.makedirs(custom_server_dir, exist_ok=True)
        assert os.path.exists(custom_server_dir)
        names = set()
        volume_regex = r"(_|\s)?vol[ume-]*[\w\s]*(\d+)"
        for file in files:
            logging.info("Trying to import %s (dir: %s)", file, os.path.isdir(file))
            media_name = name
            if not name:
                match = re.search(r"(\[[\w ]*\]|\d+[.-:]?)?\s*([\w\-]+\w+[\w';:\. ]*\w[!?]*)(.*\.\w+)$", re.sub(volume_regex, "", os.path.basename(file)))
                if not match:
                    if os.path.isdir(file):
                        self.import_media(map(lambda x: os.path.join(file, x), os.listdir(file)), media_type, link=link, no_update=True)
                        continue
                assert match
                media_name = match.group(2)
                logging.info("Detected name %s", media_name)
            if os.path.isdir(file):
                shutil.move(file, os.path.join(custom_server_dir, name or ""))
            else:
                path = os.path.join(custom_server_dir, media_name)
                os.makedirs(path, exist_ok=True)
                dest = os.path.join(path, os.path.basename(file))
                logging.info("Importing to %s", dest)
                func(file, dest)
            if media_name not in names:
                if not any([x["name"] == media_name for x in self.get_media_in_library()]):
                    self.search_add(media_name, server_id=local_server_id, exact=True)
                names.add(media_name)

        if not no_update:
            [self.update_media(media_data) for media_data in self._get_media(name=local_server_id)]

    def maybe_fetch_extra_cookies(self):
        for server in self.get_servers():
            if server.is_protected:
                server.session_get_protected("https://" + server.domain)

    def clean(self, remove_disabled_servers=False, include_external=False, remove_read=False, remove_not_on_disk=False, bundles=False):
        if remove_not_on_disk:
            for media_data in [x for x in self.get_media_in_library() if not os.path.exists(self.settings.get_chapter_metadata_file(x))]:
                logging.info("Removing metadata for %s because it doesn't exist on disk", media_data["name"])
                self.remove_media(media_data)
        media_dirs = {self.settings.get_media_dir(media_data): media_data for media_data in self.get_media_in_library()}
        if bundles:
            logging.info("Removing all bundles")
            shutil.rmtree(self.settings.bundle_dir)
            self.bundles.clear()
        for dir in os.listdir(self.settings.media_dir):
            server = self.get_server(dir)
            server_path = os.path.join(self.settings.media_dir, dir)
            if server:
                if include_external or not server.external:
                    for media_dir in os.listdir(server_path):
                        media_path = os.path.join(server_path, media_dir)
                        if media_path not in media_dirs:
                            logging.info("Removing %s because it has been removed", media_path)
                            shutil.rmtree(media_path)
                        elif remove_read:
                            media_data = media_dirs[media_path]
                            for chapter_data in self._get_sorted_chapters(media_data):
                                chapter_path = server._get_dir(media_data, chapter_data, skip_create=True)
                                if chapter_data["read"] and os.path.exists(chapter_path):
                                    logging.info("Removing %s because it has been read", chapter_path)
                                    shutil.rmtree(chapter_path)

            elif remove_disabled_servers:
                logging.info("Removing %s because it is not enabled", server_path)
                shutil.rmtree(server_path)

    def stats(self, username=None, media_type=None, refresh=False, statGroup=StatGroup.NAME, sortIndex=SortIndex.NAME, reverse=False, min_count=0, min_score=1, details=False, detailsType="name"):
        statsFile = self.settings.get_stats_file()
        data = None
        saved_data = self.state.read_file_as_dict(statsFile) if os.path.exists(statsFile) else {}
        if not refresh:
            data = saved_data.get(username if username else "", None)
        if not data:
            logging.info("Loading stats")
            data = list(self.get_primary_tracker().get_full_list_data(user_name=username))
            saved_data.update({username if username else "": data})
            self.state.save_to_file(statsFile, saved_data)
        assert data
        if media_type:
            data = list(filter(lambda x: x["media_type"] == media_type, data))
        groupedData = stats.group_entries(data, min_score=min_score)[statGroup.value]
        sortedData = stats.compute_stats(groupedData, sortIndex.value, reverse=reverse, min_count=min_count, details=details, detailsType=detailsType)
        print("IDX", stats.get_header_str(statGroup, details, detailsType=detailsType))
        for i, entry in enumerate(sortedData):
            print(f"{i+1:3} {stats.get_entry_str(entry, details)}")
