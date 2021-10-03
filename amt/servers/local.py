import os
import re

from ..server import Server
from ..util.media_type import MediaType


def get_local_server_id(media_type):
    if media_type == MediaType.ANIME:
        return LocalAnimeServer.id
    elif media_type == MediaType.MANGA:
        return LocalMangaServer.id
    elif media_type == MediaType.NOVEL:
        return LocalLightNovelServer.id


class LocalServer(Server):
    external = True

    id_formatter_regex = re.compile(r"\W+")
    number_regex = re.compile(r"(\d+\.?\d*)[ \.]")

    def get_number_from_file_name(self, file_name):
        matches = self.number_regex.findall(file_name.replace("_", " "))
        return float(max(matches, key=len)) if matches else 0

    def _create_media_data(self, file_name):
        assert "/" not in file_name
        return self.create_media_data(id=self.id_formatter_regex.sub("_", file_name), name=file_name, dir_name=file_name)

    def get_import_media_dest(self, media_name, file_name):
        media_data = self._create_media_data(media_name)
        self.update_chapter_data(media_data, id=file_name, title=file_name, number=self.get_number_from_file_name(file_name.replace(media_name, "")))
        chapter_data = media_data["chapters"][file_name]
        return os.path.join(self.settings.get_chapter_dir(media_data, chapter_data), file_name)

    def get_media_list(self, limit=None):
        return [self._create_media_data(file_name) for file_name in os.listdir(self.settings.get_server_dir(self.id))][:limit] if os.path.exists(self.settings.get_server_dir(self.id)) else []

    def update_media_data(self, media_data):
        media_dir = self.settings.get_media_dir(media_data)
        for file_name in os.listdir(media_dir):
            chapter_path = os.path.join(media_dir, file_name)
            if os.path.isdir(chapter_path):
                pages = os.listdir(chapter_path)
                if pages:
                    title = pages[0]
                    number = float(file_name)
                    if number % 1 == 0:
                        number = int(number)
                    self.update_chapter_data(media_data, id=number, title=title, number=number)

    def is_fully_downloaded(self, media_data, chapter_data):
        return os.path.exists(self.settings.get_chapter_dir(media_data, chapter_data, skip_create=True))

    def download_chapter(self, media_data, chapter_data, **kwargs):
        return False


class LocalAnimeServer(LocalServer):
    id = "local_anime"
    media_type = MediaType.ANIME


class LocalMangaServer(LocalServer):
    id = "local_manga"
    media_type = MediaType.MANGA


class LocalLightNovelServer(LocalServer):
    id = "local_novel"
    media_type = MediaType.NOVEL
