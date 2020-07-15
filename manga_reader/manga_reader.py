import manga_reader.servers
from manga_reader.server import Server
from manga_reader.settings import Settings
import json

import importlib
import pkgutil
import inspect

SERVERS = []
for _finder, name, _ispkg in pkgutil.iter_modules(manga_reader.servers.__path__, manga_reader.servers.__name__ + '.'):
    module = importlib.import_module(name)
    for _name, obj in dict(inspect.getmembers(module)).items():
        if inspect.isclass(obj) and issubclass(obj, Server) and obj != Server:
            SERVERS.append(obj)


class MangaReader:

    def __init__(self, class_list=SERVERS, settings=None):
        self.settings = settings if settings else Settings()
        self._servers = {}
        for cls in class_list:
            if cls.id:
                instance = cls(self.settings)
                self._servers[instance.id] = instance
        self.state = {}

    def load_state(self):
        with open(self.settings.get_metadata(), 'r') as jsonFile:
            self.state = json.load(jsonFile)

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

    def get_manga_in_library(self):
        return self.state.values()

    def search_for_manga(self, term):
        result = []
        for server in self.get_servers():
            result += server.search(term)
        return result

    def mark_chapters_until_n_as_read(self, manga_data, N):
        """Marks all chapters whose numerical index <=N as read"""
        for chapter in manga_data["chapters"].values():
            if chapter["number"] <= N:
                chapter["read"] = True

    def download_unread_chapters(self):
        """Downloads all chapters that are not read"""
        for manga_data in self.state.values():
            for chapter in manga_data["chapters"].values():
                server = self._servers[manga_data["server_id"]]
                if not chapter["read"]:
                    server.download_chapter(manga_data, chapter)

    def update(self, download=False):
        new_chapters = []
        for manga_data in self.state.values():
            new_chapters += self.update_manga(manga_data, download)
        return new_chapters

    def update_manga(self, manga_data, download=False, limit=None):
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
                server.download_chapter(manga_data, chapter_data)
        return new_chapters
