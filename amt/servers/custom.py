import logging
import os

from ..server import Server


def get_number(file_name, index):
    try:
        return float(file_name.split(" ")[0])
    except ValueError:
        return index


class CustomServer(Server):
    id = 'custom_server'
    external = True

    def get_media_list(self):
        return [self.create_media_data(dir, dir) for dir in os.listdir(self.settings.get_server_dir(self.id))]

    def update_media_data(self, media_data):
        root = self.settings.get_media_dir(media_data)
        _, dirNames, fileNames = next(os.walk(root))
        dirNames.sort()
        fileNames.sort()
        for i, fileName in enumerate(fileNames):
            self.update_chapter_data(media_data, fileName, fileName, get_number(fileName, i))
        for i, dirName in enumerate(dirNames):
            self.update_chapter_data(media_data, dirName + "/*", dirName, get_number(dirName, i))

    def is_fully_downloaded(self, dir_path):
        return True

    def get_dir(self, media_data, chapter_data):
        return os.path.join(self.settings.get_media_dir(media_data), chapter_data["id"])

    def get_children(self, media_data, chapter_data):
        return os.path.join(self.settings.get_media_dir(media_data), chapter_data["id"])

    def download_chapter(self, media_data, chapter_data, page_limit=None):
        return True, False
