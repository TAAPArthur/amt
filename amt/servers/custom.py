import os
import re

from ..server import ANIME, MANGA, NOVEL, Server


def get_local_server_id(media_type):
    if media_type == ANIME:
        return LocalAnimeServer.id
    elif media_type == MANGA:
        return LocalMangaServer.id
    elif media_type == NOVEL:
        return LocalLightNovelServer.id


class CustomServer(Server):
    external = True
    number_regex = re.compile(r"(\d+\.?\d*)[ \.]")
    id_formatter_regex = re.compile(r"\W+")

    def get_media_list(self, limit=None):
        return [self.create_media_data(id=self.id_formatter_regex.sub("_", dir), name=dir, dir_name=dir) for dir in os.listdir(self.settings.get_server_dir(self.id))][:limit] if os.path.exists(self.settings.get_server_dir(self.id)) else []

    def update_media_data(self, media_data):
        for fileName in os.listdir(self.settings.get_media_dir(media_data)):
            matches = self.number_regex.findall(fileName)
            self.update_chapter_data(media_data, id=fileName, title=fileName, number=float(max(matches, key=len)) if matches else 0)

    def is_fully_downloaded(self, media_data, chapter_data):
        return os.path.exists(os.path.join(self.settings.get_media_dir(media_data), chapter_data["id"]))

    def _get_dir(self, media_data, chapter_data):
        chapter = os.path.join(self.settings.get_media_dir(media_data), chapter_data["id"])
        return chapter if os.path.isdir(chapter) else self.settings.get_media_dir(media_data)

    def get_children(self, media_data, chapter_data):
        chapter = os.path.join(self.settings.get_media_dir(media_data), chapter_data["id"])
        if os.path.isdir(chapter):
            return chapter + "/*"
        return chapter

    def download_chapter(self, media_data, chapter_data, page_limit=None):
        return False


class LocalAnimeServer(CustomServer):
    id = "local_anime"
    media_type = ANIME


class LocalMangaServer(CustomServer):
    id = "local_manga"
    media_type = MANGA


class LocalLightNovelServer(CustomServer):
    id = "local_novels"
    media_type = NOVEL
