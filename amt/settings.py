import json
import logging
import os
import subprocess
from datetime import datetime
from pathlib import Path
from shlex import quote
from subprocess import CalledProcessError

APP_NAME = "amt"


class Settings:

    auto_upgrade_state = True
    password_manager_enabled = True
    password_save_cmd = "tpm insert {}"
    password_load_cmd = "tpm show {}"
    bundle_cmds = {
        "cbz": "zip {:2} {:1}",
        "pdf": "convert -density 100 -units PixelsPerInch {:1} {:2}"
    }
    bundle_format = "pdf"

    threads = 8

    anime_viewer = "mpv {:1} --title='{title}'"
    manga_viewer = "zathura {}"
    page_viewer = "sxiv {}"
    segment_viewer = "cat {} | mpv -"

    no_save_session = False
    free_only = False
    shell = True
    max_retires = 5
    status_to_retry = [500, 502, 504]
    force_odd_pages = True
    env_override_prefix = "PASSWORD_OVERRIDE_"
    incapsula_prompt = ""

    def __init__(self, home=Path.home(), no_save_session=None, no_load=False):
        self.config_dir = os.getenv('XDG_CONFIG_HOME', os.path.join(home, ".config", APP_NAME))
        self.cache_dir = os.getenv('XDG_CACHE_HOME', os.path.join(home, ".cache", APP_NAME))
        self.data_dir = os.getenv('XDG_DATA_HOME', os.path.join(home, ".local/share", APP_NAME))
        self.bundle_dir = os.path.join(self.data_dir, "Bundles")
        self.media_dir = os.path.join(self.data_dir, "Media")
        self.no_save_session = no_save_session
        if not no_load:
            self.load()

    def init(self):
        os.makedirs(self.config_dir, exist_ok=True)
        os.makedirs(self.cache_dir, exist_ok=True)
        os.makedirs(self.data_dir, exist_ok=True)
        os.makedirs(self.bundle_dir, exist_ok=True)
        os.makedirs(self.media_dir, exist_ok=True)

    @classmethod
    def get_members(clazz):
        return [attr for attr in dir(clazz) if not callable(getattr(clazz, attr)) and not attr.startswith("__")]

    def set(self, name, value):
        if isinstance(self.get(name), bool) and not isinstance(value, bool):
            value = value.lower() not in ["false", 0, ""]

        if isinstance(value, str) and (isinstance(self.get(name), int) or isinstance(value, float)):
            value = type(self.get(name))(value)
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

    def get_server_dir(self, server_id):
        return os.path.join(self.media_dir, server_id)

    def get_media_dir(self, media_data):
        return os.path.join(self.get_server_dir(media_data["server_id"]), media_data["name"].replace("/", "_"))

    def get_chapter_dir(self, media_data, chapter_data):
        dir = os.path.join(self.get_media_dir(media_data), "%06.1f" % chapter_data["number"])
        os.makedirs(dir, exist_ok=True)
        return dir

    def get_incapsula(self, server_id: str) -> (str, str):
        output = subprocess.check_output(self.incapsula_prompt.format(server_id), shell=self.shell, stdin=subprocess.DEVNULL).strip().decode("utf-8")
        if output.startswith("incap_ses_"):
            return output.split("=", 1)
        else:
            return "incap_ses_979_998813", output

    def get_credentials(self, server_id: str) -> (str, str):
        """Returns the saved username, password"""
        if self.env_override_prefix and os.getenv(self.env_override_prefix + server_id):
            return os.getenv(self.env_override_prefix + server_id).split("\t")
        if self.password_manager_enabled and self.password_load_cmd:
            try:
                logging.debug("Loading credentials for %s `%s`", server_id, self.password_load_cmd.format(server_id))
                output = subprocess.check_output(self.password_load_cmd.format(server_id), shell=self.shell, stdin=subprocess.DEVNULL).strip().decode("utf-8")
                login, password = output.split("\t")
                return login, password
            except subprocess.CalledProcessError:
                logging.info("Unable to load credentials for %s", server_id)

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
        arg = " ".join(map(Settings._smart_quote, img_dirs))
        name = os.path.join(self.bundle_dir, "{}_{}.{}".format(datetime.now().strftime('%Y-%m-%d_%H:%M:%S'), str(hash(arg))[1:8], self.bundle_format))
        cmd = self.bundle_cmds[self.bundle_format].format(arg, name)
        logging.info("Running cmd %s shell = %s", cmd, self.shell)
        subprocess.check_call(cmd, shell=self.shell)
        return name

    @staticmethod
    def _smart_quote(name):
        return quote(name) if name[-1] != "*" else quote(name[:-1]) + "*"

    def _open_viewer(self, viewer, name, **kwargs):
        try:
            if isinstance(name, str):
                name = Settings._smart_quote(name)
            else:
                name = " ".join(map(Settings._smart_quote, name))
            full_cmd = viewer.format(name, kwargs)
            logging.info("Running cmd %s: %s shell = %s", viewer, full_cmd, self.shell)
            subprocess.check_call(full_cmd, shell=self.shell)
            return True
        except CalledProcessError:
            return False

    def open_manga_viewer(self, name):
        return self._open_viewer(self.manga_viewer, name)

    def open_anime_viewer(self, name, title):
        return self._open_viewer(self.anime_viewer, name, title=title)

    def open_segment_viewer(self, name):
        return self._open_viewer(self.segment_viewer, name)

    def open_page_viewer(self, name):
        return self._open_viewer(self.page_viewer, name)
