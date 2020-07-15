from pathlib import Path
import json
import os
import subprocess

APP_NAME = "manager-reader"


class Settings:

    password_manager_enabled = False
    password_save_cmd = "tpm insert {}"
    password_load_cmd = "tpm show {}"
    manga_viewer_cmd = ""
    cache_requests = False
    cache = False
    no_save_session = False

    def __init__(self, home=Path.home(), no_save_session=None, no_load=False):
        self.config_dir = os.getenv('XDG_CONFIG_HOME', os.path.join(home, ".config", APP_NAME))
        self.cache_dir = os.getenv('XDG_CACHE_HOME', os.path.join(home, ".cache", APP_NAME))
        self.data_dir = os.getenv('XDG_DATA_HOME', os.path.join(home, ".local/share", APP_NAME))
        self.no_save_session = no_save_session
        if not no_load:
            self.load()

    def init(self):
        os.makedirs(self.config_dir, exist_ok=True)
        os.makedirs(self.cache_dir, exist_ok=True)
        os.makedirs(self.data_dir, exist_ok=True)

    def _get_members(self):
        return [attr for attr in dir(self) if not callable(getattr(self, attr)) and not attr.startswith("__")]

    def save(self):
        with open(self.get_settings_file(), 'w') as f:
            settings_to_save = {}
            members = self._get_members()
            for attr in members:
                settings_to_save[attr] = getattr(self, attr)
            json.dump(settings_to_save, f, indent=4)

    def load(self):
        try:
            with open(self.get_settings_file(), 'r') as f:
                saved_settings = json.load(f)
                members = self._get_members()
                for attr in members:
                    if attr in saved_settings:
                        setattr(self, attr, saved_settings[attr])
        except FileNotFoundError:
            pass

    def get_settings_file(self):
        return os.path.join(self.config_dir, "settings.json")

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

    def get_credentials(self, server_id: str) -> (str, str):
        """Returns the saved username, password"""
        if self.password_manager_enabled and self.password_load_cmd:
            try:
                output = subprocess.check_output(self.password_load_cmd.format(server_id), shell=True, stdin=subprocess.DEVNULL).strip().decode("utf-8")
                login, password = output.split("\t")
                return login, password
            except subprocess.CalledProcessError:
                pass

    def store_credentials(self, server_id, username, password):
        """Stores the username, password for the given server_id"""
        if self.password_manager_enabled and self.password_save_cmd:
            process = subprocess.Popen(self.password_save_cmd.format(server_id), shell=True, stdin=subprocess.PIPE)
            process.communicate(input=bytes("{}\t{}".format(username, password), "utf8"))
