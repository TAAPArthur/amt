import json
import logging


def json_decoder(obj):
    if "server_id" in obj:
        return MediaData(obj)
    if "number" in obj:
        return ChapterData(obj)
    return obj


class State:
    version = 1

    def __init__(self, settings):
        self.settings = settings
        self.bundles = {}
        self.media = {}
        self.all_media = {}
        self.hashes = {}

    @staticmethod
    def get_hash(json_dict):
        json_str = json.dumps(json_dict, indent=4, sort_keys=True)
        return hash(json_str), json_str

    def read_file_as_dict(self, file_name, object_hook=json_decoder):
        try:
            with open(file_name, "r") as jsonFile:
                logging.debug("Loading file %s", file_name)

                json_dict = json.load(jsonFile, object_hook=object_hook)
                self.hashes[file_name] = State.get_hash(json_dict)[0]
                return json_dict
        except FileNotFoundError:
            return {}

    def save_to_file(self, file_name, json_dict):
        h, json_str = State.get_hash(json_dict)
        if self.hashes.get(file_name, 0) == h:
            return False
        self.hashes[file_name] = h
        try:
            with open(file_name, "w") as jsonFile:
                jsonFile.write(json_str)
            logging.info("Persisting state to %s", file_name)
        except FileNotFoundError:
            return False

        return True

    def save(self):
        self.save_to_file(self.settings.get_bundle_metadata_file(), self.bundles)
        self.save_to_file(self.settings.get_metadata(), self.all_media)
        for media_data in self.media.values():
            self.save_to_file(self.settings.get_chapter_metadata_file(media_data), media_data.chapters)

    def load(self):
        self.load_bundles()
        self.load_media()

    def load_bundles(self):
        self.bundles = self.read_file_as_dict(self.settings.get_bundle_metadata_file())

    def load_media(self):
        self.all_media = self.read_file_as_dict(self.settings.get_metadata())
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

    def is_out_of_date(self):
        return self.all_media.get("version", 0) != self.version

    def update_verion(self):
        self.all_media["version"] = self.version

    def configure_media(self, server_list):
        for key in list(self.media.keys()):
            if self.media[key]["server_id"] not in server_list:
                self.disabled_media[key] = self.media[key]
                del self.media[key]

        for key in list(self.disabled_media.keys()):
            if self.disabled_media[key]["server_id"] in server_list:
                self.media[key] = self.disabled_media[key]
                del self.disabled_media[key]

    def mark_bundle_as_read(self, bundle_name):
        bundled_data = self.bundles[bundle_name]
        for data in bundled_data:
            self.media[data["media_id"]]["chapters"][data["chapter_id"]]["read"] = True


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

    @property
    def global_id(self):
        return "{}:{}{}{}".format(self["server_id"], self["id"], (self["season_id"] if self["season_id"] else ""), self.get("lang", "")[:3])


class ChapterData(dict):
    def __init__(self, backing_map):
        super().__init__(backing_map)
