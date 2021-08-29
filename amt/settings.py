import getpass
import json
import logging
import os
import re
import subprocess
from datetime import datetime
from pathlib import Path
from shlex import quote
from subprocess import DEVNULL, CalledProcessError
from threading import Lock

from .server import ANIME, MANGA, NOVEL

APP_NAME = "amt"


class Settings:

    # env
    allow_env_override = True
    env_override_prefix = "AMT_"

    # Password manager related settings
    password_manager_enabled = True
    password_save_cmd = "tpm insert {}"
    password_load_cmd = "tpm show {}"
    credential_separator = "\t"
    password_override_prefix = "PASSWORD_OVERRIDE_"

    _lock = Lock()

    # External commands and formats
    bundle_cmds = {
        "cbz": "zip {name} {files}",
        "pdf": "convert -density 100 -units PixelsPerInch {name} {files}"
    }
    bundle_format = "cbz"
    bundle_viewer = "zathura {media}"
    converters = [
        ("ts", "mp4", "cat {input} > {output}", "rm {}"),
    ]

    # HTTP related; Generally used as args to requests
    bs4_parser = "html.parser"
    max_retires = 3
    status_to_retry = [429, 500, 502, 503, 504]
    user_agent = "Mozilla/5.0"

    # Cookies
    cookie_files = ["/tmp/cookies.txt"]

    # MISC
    allow_only_official_servers = False
    free_only = False
    no_load_session = False
    no_save_session = False
    shell = True
    suppress_cmd_output = False

    # Server or media specific settings
    specific_settings = {
        "viewer": {
            NOVEL: "zathura {media}",
            ANIME: "mpv --sub-file-paths=\"$PWD\" --sub-auto=all --title={title} {media}",
            MANGA: "sxiv {media}"
        }
    }
    auto_replace = True
    chapter_title_format = "{media_name}: #{chapter_number} {chapter_title}"
    disable_ssl_verification = False
    force_odd_pages = True
    text_languages = ("en", "en-US", "English")
    threads = 8  # per server thread count

    def __init__(self, home=Path.home(), no_save_session=None, no_load=False):
        self.config_dir = os.getenv("XDG_CONFIG_HOME", os.path.join(home, ".config", APP_NAME))
        self.cache_dir = os.getenv("XDG_CACHE_HOME", os.path.join(home, ".cache", APP_NAME))
        self.data_dir = os.getenv("XDG_DATA_HOME", os.path.join(home, ".local/share", APP_NAME))
        self.bundle_dir = os.path.join(self.data_dir, "Bundles")
        self.media_dir = os.path.join(self.data_dir, "Media")
        self.no_save_session = no_save_session
        if not no_load:
            self.load()
        os.makedirs(self.config_dir, exist_ok=True)
        os.makedirs(self.cache_dir, exist_ok=True)
        os.makedirs(self.data_dir, exist_ok=True)
        os.makedirs(self.bundle_dir, exist_ok=True)
        os.makedirs(self.media_dir, exist_ok=True)
        self._replacements = None

    def get_cookie_file(self):
        return os.path.join(self.cache_dir, "cookies.txt")

    def get_stats_file(self):
        return os.path.join(self.cache_dir, "stats.json")

    def get_replacement_file(self):
        return os.path.join(self.config_dir, "replacements.txt")

    def get_replacement_dir(self):
        return os.path.join(self.config_dir, "replacements.d")

    def get_replacements(self, media_data=None):
        def parse_file(f, replacements):
            try:
                with open(f, 'r') as f:
                    for line in f:
                        line = line.strip()
                        if line and line[0] != "#":
                            if line.count("/") == 1:
                                src, target = line.split("/")
                            else:
                                _, src, target, _ = line.split("/")
                            replacements.append((src, target))
            except FileNotFoundError:
                pass
        with self._lock:
            if self._replacements is None:
                self._replacements = {"": []}
                parse_file(self.get_replacement_file(), self._replacements[""])
                if os.path.exists(self.get_replacement_dir()):
                    for specific_replacement_file in os.listdir(self.get_replacement_dir()):
                        self._replacements[specific_replacement_file] = []
                        parse_file(os.path.join(self.get_replacement_dir(), specific_replacement_file), self._replacements[specific_replacement_file])

        yield from self._replacements[""]

        for key in [media_data["server_id"], media_data["name"], media_data.global_id, id] if isinstance(media_data, dict) else [media_data]:
            if key and key in self._replacements:
                yield from self._replacements[key]

    def auto_replace_if_enabled(self, text, media_data=None):
        if self.get_field("auto_replace", media_data=media_data):
            for src, target in self.get_replacements(media_data=media_data):
                text = re.sub(src, target, text)
        return text

    def is_allowed_text_lang(self, lang, media_data):
        return lang in self.get_field("text_languages", media_data)

    def get_num_threads(self, media_data=None):
        return self.get_field("threads", media_data)

    def skip_ssl_verification(self, server_id=None):
        return self.get_field("disable_ssl_verification", server_id)

    def get_cookie_files(self):
        yield self.get_cookie_file()
        yield from map(os.path.expanduser, self.cookie_files)

    @classmethod
    def get_members(clazz):
        return [attr for attr in dir(clazz) if not callable(getattr(clazz, attr)) and not attr.startswith("_")]

    def set_field(self, name, value, server_or_media_id=None):
        current_field = self.get_field(name, server_or_media_id)
        if isinstance(current_field, bool) and not isinstance(value, bool):
            value = value.lower() not in ["false", 0, ""]

        if isinstance(value, str) and (isinstance(current_field, int) or isinstance(value, float)):
            value = type(current_field)(value)
        if server_or_media_id:
            if not name in self.specific_settings:
                self.specific_settings[name] = {}
            self.specific_settings[name][server_or_media_id] = value
        else:
            setattr(self, name, value)
        return value

    def get_field(self, name, media_data=None):
        for key in [media_data.global_id, media_data["name"], media_data["server_id"], media_data["media_type"]] if isinstance(media_data, dict) else [media_data]:
            if name in self.specific_settings and key in self.specific_settings[name]:
                return self.specific_settings[name][key]
        return getattr(self, name)

    def save(self):
        with open(self.get_settings_file(), "w") as f:
            settings_to_save = {}
            members = Settings.get_members()
            for attr in members:
                settings_to_save[attr] = self.get_field(attr)
            json.dump(settings_to_save, f, indent=4)

    def load(self):
        try:
            with open(self.get_settings_file(), "r") as f:
                saved_settings = json.load(f)
                for attr in Settings.get_members():
                    if attr in saved_settings:
                        self.set_field(attr, saved_settings[attr])
        except FileNotFoundError:
            pass
        if self.allow_env_override:
            for attr in Settings.get_members():
                env_var = os.getenv(f"{self.env_override_prefix}{attr.upper()}")
                if env_var is not None:
                    self.set_field(attr, env_var)
        os.environ["USER_AGENT"] = self.user_agent

    def get_settings_file(self):
        return os.path.join(self.config_dir, "settings.json")

    def get_metadata(self):
        return os.path.join(self.data_dir, "metadata.json")

    def get_chapter_metadata_file(self, media_data):
        return os.path.join(self.get_media_dir(media_data), "chapter_metadata.json")

    def get_bundle_metadata_file(self):
        return os.path.join(self.data_dir, "bundles.json")

    def get_server_dir(self, server_id):
        return os.path.join(self.media_dir, server_id)

    def get_media_dir(self, media_data):
        return os.path.join(self.get_server_dir(media_data["server_id"]), media_data["dir_name"])

    def get_chapter_dir(self, media_data, chapter_data, skip_create=False):
        dir = os.path.join(self.get_media_dir(media_data), "%06.1f" % chapter_data["number"])
        if not skip_create:
            os.makedirs(dir, exist_ok=True)
        return dir

    def get_credentials(self, server_id: str) -> (str, str):
        """Returns the saved username, password"""
        if self.password_override_prefix:
            var = os.getenv(self.password_override_prefix + server_id) or os.getenv(self.password_override_prefix + server_id.upper())
            if var:
                return var.split(self.credential_separator)
        if self.password_manager_enabled:
            with self._lock:
                if self.password_load_cmd:
                    try:
                        logging.debug("Loading credentials for %s `%s`", server_id, self.password_load_cmd.format(server_id))
                        output = subprocess.check_output(self.password_load_cmd.format(server_id), shell=self.shell, stdin=subprocess.DEVNULL).strip().decode("utf-8")
                        login, password = output.split(self.credential_separator)
                        return login, password
                    except subprocess.CalledProcessError:
                        logging.info("Unable to load credentials for %s", server_id)
                else:
                    return input("Username: "), getpass.getpass()

    def store_credentials(self, server_id, username, password=None):
        """Stores the username, password for the given server_id"""
        if password is None:
            password = getpass.getpass()
        if self.password_manager_enabled and self.password_save_cmd:
            logging.debug("Storing credentials for %s", server_id)
            process = subprocess.Popen(self.password_save_cmd.format(server_id), shell=self.shell, stdin=subprocess.PIPE)
            process.communicate(input=bytes(f"{username}{self.credential_separator}{password}", "utf8"))

    def get_secret(self, server_id: str) -> (str, str):
        result = self.get_credentials(server_id)
        return result[0] if result else None

    def store_secret(self, server_id, secret):
        self.store_credentials(server_id, secret, "token")

    def run_cmd(self, cmd, wd=None):
        subprocess.check_call(cmd, stdout=DEVNULL if self.suppress_cmd_output else None, shell=self.shell, cwd=wd) if isinstance(cmd, str) else cmd()

    @staticmethod
    def _smart_quote(name):
        return quote(name) if name[-1] != "*" else quote(name[:-1]) + "*"

    def bundle(self, img_dirs):
        arg = " ".join(map(Settings._smart_quote, img_dirs))
        name = os.path.join(self.bundle_dir, "{}_{}.{}".format(datetime.now().strftime("%Y-%m-%d_%H:%M:%S"), str(hash(arg))[1:8], self.bundle_format))
        cmd = self.bundle_cmds[self.bundle_format].format(files=arg, name=name)
        logging.info("Running cmd %s shell = %s", cmd, self.shell)
        self.run_cmd(cmd)
        return name

    def _open_viewer(self, viewer, name, title, wd=None):
        try:
            assert isinstance(name, str)
            name = Settings._smart_quote(name)
            cmd = viewer.format(media=name, title=quote(title)) if title else viewer.format(name)
            logging.info("Running cmd %s: %s shell = %s, wd=%s", viewer, cmd, self.shell, wd)
            self.run_cmd(cmd, wd=wd)
            return True
        except CalledProcessError:
            return False

    def open_viewer(self, files, media_data, chapter_data, wd):
        viewer = self.get_field("viewer", media_data)
        title = self.get_field("chapter_title_format", media_data).format(media_name=media_data["name"], chapter_number=chapter_data["number"], chapter_title=chapter_data["title"])
        return self._open_viewer(viewer, files, title=title, wd=wd)

    def open_bundle_viewer(self, bunldle_path, media_data=None):
        title = os.path.basename(bunldle_path)
        return self._open_viewer(self.bundle_viewer, bunldle_path, title=title)

    def convert(self, extension, files, destWithoutExt):
        for ext, targetExt, cmd, cleanupCmd in self.converters:
            if ext == extension:
                targetFile = self._smart_quote(f"{destWithoutExt}.{targetExt}")
                logging.info("Converting %s to %s", files, targetFile)
                self.run_cmd(cmd.format(input=files, output=targetFile))
                self.run_cmd(cleanupCmd.format(files))
