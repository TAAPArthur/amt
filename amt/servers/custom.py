import logging
import os
import re
from shlex import quote

from ..server import ANIME, MANGA, NOT_ANIME, Server


class CustomServer(Server):
    id = 'custom_server'
    external = True
    media_type = NOT_ANIME | ANIME
    number_regex = re.compile(r"(\d+\.?\d*)")

    def get_media_list(self):
        return [self.create_media_data(dir, dir, dir_name=dir) for dir in os.listdir(self.settings.get_server_dir(self.id))] if os.path.exists(self.settings.get_server_dir(self.id)) else []

    def update_media_data(self, media_data):
        root = self.settings.get_media_dir(media_data)
        _, dirNames, fileNames = next(os.walk(root))
        dirNames.sort()
        fileNames.sort()
        for i, fileName in enumerate(fileNames):
            self.update_chapter_data(media_data, fileName, fileName, float(self.number_regex.search(fileName).group(1)))
        for i, dirName in enumerate(dirNames):
            self.update_chapter_data(media_data, dirName, dirName, float(self.number_regex.search(dirName).group(1)))

    def is_fully_downloaded(self, media_data, chapter_data):
        return os.path.exists(os.path.join(self.settings.get_media_dir(media_data), chapter_data["id"]))

    def get_children(self, media_data, chapter_data):
        chapter = os.path.join(self.settings.get_media_dir(media_data), chapter_data["id"])
        if os.path.isdir(chapter):
            return quote(chapter) + "/*"
        return quote(chapter)

    def download_chapter(self, media_data, chapter_data, page_limit=None):
        return True, False
