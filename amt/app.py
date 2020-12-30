import logging
import os
import re
import shutil

from .media_reader import MangaReader
from .server import ANIME, MANGA, NOT_ANIME, NOVEL
from .servers.custom import get_local_server_id

TYPE_NAMES = {MANGA: "Manga", NOVEL: "Novel", ANIME: "Anime"}


class Application(MangaReader):
    auto_select = False

    def save(self):
        self.save_session_cookies()
        self.save_state()

    def print_results(self, results):
        for i, result in enumerate(results):
            print("{:4}| {}:{}\t{} {} ({})".format(i, result["server_id"], result["id"], result["name"], result["season_title"], TYPE_NAMES[result["media_type"]]))

    def select_media(self, results, prompt):
        index = 0

        if not self.auto_select and len(results) > 1:
            index = input(prompt)
        try:
            return results[int(index)]
        except (ValueError, IndexError):
            logging.warning("Invalid input; skipping")
            return None

    def search_add(self, term, server_id=None, media_type=None, exact=False):
        results = self.search_for_media(term, server_id=server_id, media_type=media_type, exact=exact)
        if len(results) == 0:
            return
        self.print_results(results)

        media_data = self.select_media(results, "Select media to add: ")
        if media_data:
            self.add_media(media_data)
        return media_data

    def add_from_url(self, url):
        for server in self.get_servers():
            if server.can_stream_url(url):
                media_data = server.get_media_data_from_url(url)
                if media_data:
                    self.add_media(media_data)
                return media_data

    def get_media(self, term, media_type=None, stream=False, start=0, end=0):
        results = self.search_for_media(term, media_type=media_type, exact=False)
        self.print_results(results)
        media_data = self.select_media(results, "Select media to add: ")
        if media_data:
            self.update_media(media_data)
            server = self.get_server(media_data["server_id"])

            for chapter in self.get_chapters_in_range(media_data, start=start, end=end):
                if stream:
                    url = server.get_stream_url(media_data, chapter)
                    self.stream(url)
                else:
                    server.download_chapter(media_data, chapter)
        else:
            logging.info("Could not find media")

    def load_from_tracker(self, user_id=None, user_name=None, media_type_filter=None, exact=True, local_only=False, update_progress_only=False):
        tracker = self.get_primary_tracker()
        data = tracker.get_tracker_list(user_name=user_name) if user_name else tracker.get_tracker_list(id=user_id)
        count = 0
        new_count = 0

        def clean_name(x):
            return x.lower().replace(" ", "")

        unknown_media = []
        for entry in data:
            media_type = ANIME if entry["anime"] else NOT_ANIME
            if media_type_filter and not media_type & media_type_filter:
                logging.debug("Skipping %s", entry)
                continue
            media_data = self.is_added(tracker.id, entry["id"])
            if not media_data:
                if update_progress_only:
                    continue
                clean_entry_name = clean_name(entry["name"])
                prefix_entry_name = clean_entry_name.split(":")[0]

                known_matching_media = list(filter(lambda x: media_type & x["media_type"] and (
                    clean_entry_name == clean_name(x["name"]) or clean_name(x["name"]).startswith(clean_entry_name)
                    or clean_entry_name == clean_name(x["season_title"])
                ), self.get_media_in_library()))
                if not known_matching_media and not exact:
                    known_matching_media = list(filter(lambda x: media_type & x["media_type"] and (
                        prefix_entry_name == clean_name(x["name"]) or clean_name(x["name"]).startswith(prefix_entry_name)
                    ), self.get_media_in_library()))
                if known_matching_media:
                    logging.debug("Checking among known media")
                    media_data = self.select_media(known_matching_media, "Select from known media: ")

                elif not local_only:
                    if not media_data:
                        media_data = self.search_add(entry["name"], media_type=media_type, exact=True)
                    if not media_data and not exact:
                        media_data = self.search_add(entry["name"].split(":")[0], media_type=media_type, exact=False)
                    if not media_data and not exact:
                        prefix = re.sub(r"\W*$", "", entry["name"])
                        if prefix != entry["name"]:
                            media_data = self.search_add(prefix, media_type=media_type, exact=False)
                if not media_data:
                    logging.info("Could not find media %s", entry["name"])
                    unknown_media.append(entry["name"])
                    continue

                self.track(tracker.id, self._get_global_id(media_data), entry["id"], entry["name"])
                new_count += 1
            else:
                logging.debug("Already tracking %s %d", media_data["name"], entry["progress"])

            if entry["progress"] > media_data["progress"]:
                self.mark_chapters_until_n_as_read(media_data, entry["progress"])
            media_data["progress"] = entry["progress"]
            count += 1
        if unknown_media:
            logging.info("Could not find any of %s", unknown_media)

        self.list()
        return count, new_count

    def list_server_media(self, id):
        for server in self.get_servers():
            if id and server.id != id:
                continue
            for media_data in server.get_media_list():
                print("{}:{}\t{}".format(server.id, media_data["id"], media_data["name"]))

    def list(self):
        for i, result in enumerate(self.get_media_in_library()):
            last_chapter_num = self.get_last_chapter_number(result)
            last_read = self.get_last_read(result)
            print("{:4}|\t{}:{}\t{} {}\t{}/{}".format(i, result["server_id"], result["id"], result["name"], result["season_title"], last_read, last_chapter_num))

    def list_chapters(self, name):
        media_data = self._get_single_media(name=name)
        for chapter in media_data["chapters"].values():
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

    def test_login(self, server_ids=None):
        failures = False
        for server in self.get_servers():
            if server.has_login and (not server_ids or server.id in server_ids):
                if server.needs_authentication() and not server.relogin():
                    logging.error("Failed to login into %s", server.id)
                    failures = True
        return failures

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
            for chapter_data in media_data["chapters"].values():
                server.update_chapter_data(new_data, chapter_data["id"], chapter_data["title"], chapter_data["number"])
                _upgrade_dict(chapter_data, new_data["chapters"][chapter_data["id"]])

    def import_media(self, files, media_type, no_copy=False, name=None):
        func = shutil.move if no_copy else shutil.copy2

        local_server_id = get_local_server_id(media_type)
        custom_server_dir = self.settings.get_server_dir(local_server_id)
        os.makedirs(custom_server_dir, exist_ok=True)
        assert os.path.exists(custom_server_dir)
        for file in files:
            if os.path.isdir(file):
                if no_copy:
                    shutil.move(file, os.path.join(custom_server_dir, name or ""))
                else:
                    shutil.copytree(file, os.path.join(custom_server_dir, name or ""))
                    if name:
                        os.rename(os.path.join(custom_server_dir, os.path.basename(file)), os.path.join(custom_server_dir, name))
            else:
                path = os.path.join(custom_server_dir, name or os.path.basename(os.path.dirname(file)))
                os.makedirs(path, exist_ok=True)
                func(file, os.path.join(path, os.path.basename(file)))
        for media_data in self.get_server(local_server_id).get_media_list():
            if self._get_global_id(media_data) not in self.media:
                self.add_media(media_data)
