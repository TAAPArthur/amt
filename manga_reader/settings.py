from pathlib import Path
import os

APP_NAME = "manager-reader"
HOME = str()


class Settings:

    password_manager_toggle = True
    password_manager_save = None
    password_manager_load = None

    def __init__(self, home=Path.home()):
        self.config_dir = os.getenv('XDG_CONFIG_HOME', os.path.join(home, ".config", APP_NAME))
        self.cache_dir = os.getenv('XDG_CACHE_HOME', os.path.join(home, ".cache", APP_NAME))
        self.data_dir = os.getenv('XDG_DATA_HOME', os.path.join(home, ".local/share", APP_NAME))

    def init(self):
        os.makedirs(self.config_dir, exist_ok=True)
        os.makedirs(self.cache_dir, exist_ok=True)
        os.makedirs(self.data_dir, exist_ok=True)

    def get_metadata(self):
        return os.path.join(self.data_dir, "metadata.json")

    def get_chapter_dir(self, manga_data, chapter_data):
        dir = os.path.join(self.data_dir, manga_data["server_id"], manga_data["name"], chapter_data["title"])
        os.makedirs(dir, exist_ok=True)
        return dir

    def get_cover_path(self, manga_data):
        dir = os.path.join(self.data_dir, manga_data["server_id"], manga_data["name"], "cover.jpg")
        os.makedirs(dir, exist_ok=True)
        return dir
