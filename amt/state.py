import json
import logging
import os
import random

from .util.media_type import MediaType


def json_decoder(obj):
    if "server_id" in obj:
        return MediaData(obj)
    if "number" in obj:
        return ChapterData(obj)
    return obj


class State:
    version = 1.2

    def __init__(self, settings, session=None):
        self.settings = settings
        self.session = session
        self.bundles = {}
        self.media = {}
        self.all_media = {}
        self.hashes = {}
        self.cookie_hash = None
        self.server_cache = {}

        self.load()

    @staticmethod
    def get_hash(json_dict):
        if not json_dict or not any(map(lambda x: json_dict[x], json_dict)):
            return 0, ""
        json_str = json.dumps(json_dict, indent=4, sort_keys=True)
        return hash(json_str), json_str

    def read_file_as_dict(self, file_name, object_hook=json_decoder):
        try:
            with open(file_name, "r") as jsonFile:
                logging.debug("Loading file %s", file_name)

                json_dict = json.load(jsonFile, object_hook=object_hook)
                self.hashes[file_name] = State.get_hash(json_dict)[0]
                return json_dict
        except (json.decoder.JSONDecodeError, FileNotFoundError):
            return {}

    def save_to_file(self, file_name, json_dict):
        h, json_str = State.get_hash(json_dict)
        if self.hashes.get(file_name, 0) == h:
            return False
        self.hashes[file_name] = h
        os.makedirs(os.path.dirname(file_name), exist_ok=True)
        with open(file_name, "w") as jsonFile:
            jsonFile.write(json_str)
        logging.info("Persisting state to %s", file_name)

        return True

    def save(self):
        self.save_session_cookies()
        self.save_to_file(self.settings.get_metadata_file(), self.all_media)
        self.save_to_file(self.settings.get_bundle_metadata_file(), self.bundles)
        self.save_to_file(self.settings.get_server_cache_file(), self.server_cache)
        for media_data in self.media.values():
            self.save_to_file(self.settings.get_chapter_metadata_file(media_data), media_data.chapters)

    def set_session(self, session, no_load=False):
        self.session = session
        if not no_load:
            self.load_session_cookies()

    def load(self):
        self.load_media()
        self.server_cache = self.read_file_as_dict(self.settings.get_server_cache_file())
        if not self.server_cache:
            self.update_server_cache()
        self.bundles = self.read_file_as_dict(self.settings.get_bundle_metadata_file())

    def load_media(self):
        self.all_media = self.read_file_as_dict(self.settings.get_metadata_file())
        if not self.all_media:
            self.all_media = dict(media={}, disabled_media={})
        self.media = self.all_media["media"]
        self.disabled_media = self.all_media["disabled_media"]

        for key, media_data in list(self.media.items()):
            if key != media_data.global_id:
                del self.media[key]
                self.media[media_data.global_id] = media_data
            if not media_data.chapters:
                media_data.chapters = self.read_file_as_dict(self.settings.get_chapter_metadata_file(media_data))

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
                with open(path, "r") as f:
                    for line in f:
                        line = line.rstrip()
                        if not line or line[0].startswith("#"):
                            continue
                        domain, domain_specified, path, secure, expires, name, value, _ = \
                            (line + "\t").split("\t", 7)
                        self.session.cookies.set(name, value, path=path, domain=domain, secure=secure == "TRUE", expires=expires if expires else None)
            except FileNotFoundError:
                pass
        self._set_session_hash()

    def save_session_cookies(self, force=False):
        """ Save session to disk """
        if self.settings.no_save_session or not self._set_session_hash():
            return False

        os.makedirs(self.settings.cache_dir, exist_ok=True)
        with open(self.settings.get_cookie_file(), "w") as f:
            for cookie in self.session.cookies:
                l = [cookie.domain, str(cookie.domain_specified), cookie.path, str(cookie.secure).upper(), str(cookie.expires) if cookie.expires else "", cookie.name, cookie.value]
                f.write("\t".join(l) + "\n")
        return True

    def is_out_of_date(self):
        return State.version > self.all_media.get("version", 0)

    def is_out_of_date_minor(self):
        """ Is a minor state upgrade needed
        Minor upgrades are those that can before performed safely, without an
        internet connect, without user input and the new state is forwards
        compatible (the upgraded file can be used with an older program (same
        major version) without any state loss
        """
        return State.version - self.all_media.get("version", 0) < 1

    def update_verion(self):
        self.all_media["version"] = State.version

    def configure_media(self, server_list):
        for key in list(self.media.keys()):
            if self.media[key]["server_id"] not in server_list:
                self.disabled_media[key] = self.media[key]
                del self.media[key]

        for key in list(self.disabled_media.keys()):
            if self.disabled_media[key]["server_id"] in server_list:
                self.media[key] = self.disabled_media[key]
                del self.disabled_media[key]
        self.update_server_cache(server_list)

    def update_server_cache(self, server_list={}):
        self.server_cache = {server.id: {"media_type": server.media_type.value, "has_login": server.has_login()} for server in server_list.values()}

    def get_all_names(self, media_type=None, disallow_servers=False):
        names = []
        if not disallow_servers:
            for server_id in self.server_cache:
                if not media_type or self.server_cache[server_id]["media_type"] & media_type:
                    names.append(server_id)
        for media_id, media in self.media.items():
            if not media_type or media["media_type"] & media_type:
                names.append(media_id)
                if media.global_id_alt:
                    names.append(media.global_id_alt)
                names.append(media["name"])
        return names

    def get_all_single_names(self, media_type=None):
        return self.get_all_names(media_type=media_type, disallow_servers=True)

    def get_server_ids(self):
        return self.server_cache.keys()

    def get_server_ids_with_logins(self):
        return [k for k, v in self.server_cache.items() if v["has_login"]]

    def mark_bundle_as_read(self, bundle_name):
        bundled_data = self.bundles[bundle_name]
        for data in bundled_data:
            self.media[data["media_id"]]["chapters"][data["chapter_id"]]["read"] = True

    def get_lead_media_data(self, bundle):
        bundled_data = self.bundles[bundle] if isinstance(bundle, str) else bundle
        for data in bundled_data:
            return self.media[data["media_id"]]

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

    def list_media(self, name=None, media_type=None, out_of_date_only=False, tag=None, csv=False):
        for media_data in self.get_media(name=name, media_type=media_type, tag=tag):
            last_chapter_num = media_data.get_last_chapter_number()
            last_read = media_data.get_last_read()
            if not out_of_date_only or last_chapter_num != last_read:
                if csv:
                    print("\t".join([media_data.friendly_id, media_data["name"], media_data["season_title"], str(last_read), str(last_chapter_num), ",".join(media_data["tags"])]))
                else:
                    print("{}\t{} {}\t{}/{} {}".format(media_data.friendly_id, media_data["name"], media_data["season_title"], last_read, last_chapter_num, ",".join(media_data["tags"])))

    def list_chapters(self, name, show_ids=False):
        media_data = self.get_single_media(name=name)
        for chapter in media_data.get_sorted_chapters():
            print("{:4}:{}{}".format(chapter["number"], chapter["title"], ":" + chapter["id"] if show_ids else ""))


class MediaData(dict):
    def __init__(self, backing_map):
        self.chapters = {}
        if "chapters" in backing_map:
            self.chapters = backing_map["chapters"]
            del backing_map["chapters"]

        super().__init__(backing_map)

    def __getitem__(self, key):
        if key == "chapters":
            return self.chapters
        else:
            return super().__getitem__(key)

    def get_sorted_chapters(self):
        return sorted(self["chapters"].values(), key=lambda x: x["number"])

    @property
    def global_id(self):
        return "{}:{}{}{}".format(self["server_id"], self["id"], (self["season_id"] if self["season_id"] else ""), self.get("lang", "")[:3])

    @property
    def global_id_alt(self):
        return "{}:{}{}{}".format(self["server_id"], self["alt_id"], (self["season_id"] if self["season_id"] else ""), self.get("lang", "")[:3]) if self.get("alt_id", False) else None

    @property
    def friendly_id(self):
        return self.global_id if len(self.global_id) < 32 or not self.global_id_alt else self.global_id_alt

    def copy_fields_to(self, dest):
        for key in ("offset", "progress", "progress_volumes", "tags", "trackers"):
            assert key in dest
            dest[key] = self.get(key)

    def get_last_chapter_number(self):
        return max(self["chapters"].values(), key=lambda x: x["number"])["number"] if self["chapters"] else 0

    def get_last_read(self):
        return max(filter(lambda x: x["read"], self["chapters"].values()), key=lambda x: x["number"], default={"number": 0})["number"]

    def get_labels(self):
        return [self.global_id, self["name"], self["server_id"], MediaType(self["media_type"]).name]


class ChapterData(dict):
    update_state = False

    def __init__(self, backing_map):
        super().__init__(backing_map)

    def update(self, key_pars):
        super().update(key_pars)
        self.update_state = True

    def check_if_updated_and_clear(self):
        updated = self.update_state
        self.update_state = False
        return updated
