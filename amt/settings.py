from pathlib import Path
import json
import os
import subprocess
from subprocess import CalledProcessError
from datetime import date
import logging


APP_NAME = "amt"


class Settings:

    password_manager_enabled = True
    password_save_cmd = "tpm insert {}"
    password_load_cmd = "tpm show {}"
    manga_viewer_cmd = ""
    bundle_cmds = {
        "cbz": "zip {:2} {:1}",
        "pdf": "convert {:1} {:2}"
    }
    bundle_format = "pdf"
    viewers = {
        "cbz": "zathura",
        "pdf": "zathura"
    }
    no_save_session = False
    free_only = False
    shell = True

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

    @classmethod
    def get_members(clazz):
        return [attr for attr in dir(clazz) if not callable(getattr(clazz, attr)) and not attr.startswith("__")]

    def set(self, name, value):
        if isinstance(self.get(name), bool) and not isinstance(value, bool):
            value = value.lower() not in ["false", 0, ""]
        print(value, type(value))
        setattr(self, name, value)
        return value

    def get(self, name):
        return getattr(self, name)

    def save(self):
        with open(self.get_settings_file(), 'w') as f:
            settings_to_save = {}
            members = Settings.get_members()
            for attr in members:
                settings_to_save[attr] = self.get(attr)
            json.dump(settings_to_save, f, indent=4)

    def load(self):
        try:
            with open(self.get_settings_file(), 'r') as f:
                saved_settings = json.load(f)
                members = Settings.get_members()
                for attr in members:
                    if attr in saved_settings:
                        self.set(attr, saved_settings[attr])
        except FileNotFoundError:
            pass

    def get_settings_file(self):
        return os.path.join(self.config_dir, "settings.json")

    def get_metadata(self):
        return os.path.join(self.data_dir, "metadata.json")

    def get_chapter_dir(self, manga_data, chapter_data):
        dir = os.path.join(self.data_dir, manga_data["server_id"], manga_data["name"].replace(" ", "_"), "%06.1f" % chapter_data["number"])
        os.makedirs(dir, exist_ok=True)
        return dir

    def get_credentials(self, server_id: str) -> (str, str):
        """Returns the saved username, password"""
        if self.password_manager_enabled and self.password_load_cmd:
            try:
                logging.debug("Loading credentials for %s `%s`", server_id, self.password_load_cmd.format(server_id))
                output = subprocess.check_output(self.password_load_cmd.format(server_id), shell=self.shell, stdin=subprocess.DEVNULL).strip().decode("utf-8")
                login, password = output.split("\t")
                return login, password
            except subprocess.CalledProcessError:
                logging.info("Unable to load credentials for %s", server_id)
                pass

    def store_credentials(self, server_id, username, password):
        """Stores the username, password for the given server_id"""
        if self.password_manager_enabled and self.password_save_cmd:
            logging.debug("Storing credentials for %s", server_id)
            process = subprocess.Popen(self.password_save_cmd.format(server_id), shell=self.shell, stdin=subprocess.PIPE)
            process.communicate(input=bytes("{}\t{}".format(username, password), "utf8"))

    def get_secret(self, server_id: str) -> (str, str):
        result = self.get_credentials(server_id)
        return result[0] if result else None

    def store_secret(self, server_id, secret):
        self.store_credentials(server_id, secret, "token")

    def bundle(self, img_dirs):
        name = "{}_{}.{}".format(date.today(), str(hash(str(img_dirs)))[1:8], self.bundle_format)
        cmd = self.bundle_cmds[self.bundle_format].format(img_dirs, name)
        subprocess.check_call(cmd, shell=self.shell)
        return name

    def view(self, name):
        try:
            subprocess.check_call("{} {}".format(self.viewers[name.split(".")[1]], name), shell=self.shell)
            return True
        except CalledProcessError:
            return False
