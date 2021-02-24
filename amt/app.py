import logging
import os
import re
import shutil

from .media_reader import MediaReader
from .server import ANIME, MANGA, NOT_ANIME, NOVEL
from .servers.custom import get_local_server_id

TYPE_NAMES = {MANGA: "Manga", NOVEL: "Novel", ANIME: "Anime"}


class Application(MediaReader):
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

    def search_add(self, term, server_id=None, media_type=None, exact=False, servers_to_exclude=[], no_add=False):
        results = self.search_for_media(term, server_id=server_id, media_type=media_type, exact=exact, servers_to_exclude=servers_to_exclude)
        if len(results) == 0:
            return None
        print("Looking for", term)
        self.print_results(results)

        media_data = self.select_media(results, "Select media: ")
        if not no_add and media_data:
            self.add_media(media_data)
        return media_data

    def select_chapter(self, term, quality=0, **kwargs):
        media_data = self.search_add(term, **kwargs, no_add=True)
        if media_data:
            self.update_media(media_data)
            self.list_chapters(media_data)
            chapter = self.select_media(self._get_sorted_chapters(media_data), "Select episode")
            if media_data["media_type"] == ANIME:
                return self.play(name=media_data, num_list=[chapter["number"]], force_abs=True, quality=quality)
            else:
                return self.view_chapters(name=media_data, num_list=[chapter["number"]], force_abs=True)
            assert False

    def migrate(self, id):
        media_data = self._get_single_media(name=id)
        new_media_data = self.search_add(media_data["name"], media_type=media_data["media_type"], servers_to_exclude=[media_data["server_id"]])
        new_media_data["trackers"] = media_data["trackers"]
        self.mark_chapters_until_n_as_read(new_media_data, self.get_last_read(media_data))
        self.remove_media(media_data)

    def add_from_url(self, url):
        for server in self.get_servers():
            if server.can_stream_url(url):
                media_data = server.get_media_data_from_url(url)
                if media_data:
                    self.add_media(media_data)
                return media_data
        raise ValueError("Could not find media to add")

    def load_from_tracker(self, user_id=None, user_name=None, media_type_filter=None, exact=True, local_only=False, update_progress_only=False):
        tracker = self.get_primary_tracker()
        data = tracker.get_tracker_list(user_name=user_name) if user_name else tracker.get_tracker_list(id=user_id)
        count = 0
        new_count = 0

        def clean_name(x):
            return re.sub(r"\W*", "", x.lower())

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
                    alt_names = dict.fromkeys([entry["name"], entry["name"].split()[0], re.sub(r"\W*$", "", entry["name"]), re.sub(r"\W+", "", entry["name"].split()[0])])
                    for name in alt_names:
                        media_data = self.search_add(name, media_type=media_type)
                        if media_data:
                            break
                if not media_data:
                    logging.info("Could not find media %s", entry["name"])
                    unknown_media.append(entry["name"])
                    continue

                self.track(tracker.id, media_data, entry["id"], entry["name"])
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

    def list_servers(self):
        for id in sorted(self.get_servers_ids()):
            print(id)

    def list(self):
        for i, result in enumerate(self.get_media_in_library()):
            last_chapter_num = self.get_last_chapter_number(result)
            last_read = self.get_last_read(result)
            print("{:4}|\t{}\t{} {}\t{}/{}".format(i, self._get_global_id(result), result["name"], result["season_title"], last_read, last_chapter_num))

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
                if (force or server.needs_authentication()) and not server.relogin():
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
            for chapter_data in media_data["chapters"].values():
                server.update_chapter_data(new_data, chapter_data["id"], chapter_data["title"], chapter_data["number"])
                _upgrade_dict(chapter_data, new_data["chapters"][chapter_data["id"]])

    def import_media(self, files, media_type, link=False, name=None):
        func = shutil.move if not link else os.link

        local_server_id = get_local_server_id(media_type)
        custom_server_dir = self.settings.get_server_dir(local_server_id)
        os.makedirs(custom_server_dir, exist_ok=True)
        assert os.path.exists(custom_server_dir)
        names = set()
        for file in files:
            logging.info("Trying to import %s (dir: %s)", file, os.path.isdir(file))
            media_name = name
            if not name:
                match = re.search(r"(\[\w*\]|\d+[.-:]?)?\s*([\w';:\- ]+[A-z]).*\.\w+$", file)
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

        [self.update_media(media_data) for media_data in self._get_media(name=local_server_id)]

    def maybe_fetch_extra_cookies(self):
        for server in self.get_servers():
            if server.is_protected:
                server.session_get_protected("https://" + server.domain)

    def clean(self, remove_disabled_servers=False, include_external=False, remove_read=False, bundles=False):
        media_dirs = {self.settings.get_media_dir(media_data): media_data for media_data in self.get_media_in_library()}
        if bundles:
            logging.info("Removing all bundles")
            shutil.rmtree(self.settings.bundle_dir)
            self.bundles.clear()
        for dir in os.listdir(self.settings.media_dir):
            server = self.get_server(dir)
            server_path = os.path.join(self.settings.media_dir, dir)
            if not server:
                logging.info("Removing %s because it is not enabled", server_path)
                shutil.rmtree(server_path)
            else:
                if include_external or not server.external:
                    for media_dir in os.listdir(server_path):
                        media_path = os.path.join(server_path, media_dir)
                        if media_path not in media_dirs:
                            logging.info("Removing %s because it has been removed", media_path)
                            shutil.rmtree(media_path)
                        elif remove_read:
                            media_data = media_dirs[media_path]
                            for media_dir in os.listdir(server_path):
                                for chapter_data in self._get_sorted_chapters(media_data):
                                    if chapter_data["read"]:
                                        chapter_path = server._get_dir(media_data, chapter_data)
                                        logging.info("Removing %s because it has been read", chapter_path)
                                        shutil.rmtree(chapter_path)
