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

from . import cookie_manager

APP_NAME = "amt"


class Settings:

    # Password manager related settings
    password_manager_enabled = True
    password_save_cmd = "${{AMT_PASSWORD_MANAGER:-tpm}} insert {}"
    password_load_cmd = "${{AMT_PASSWORD_MANAGER:-tpm}} show {}"
    credential_separator = "\t"
    env_override_prefix = "PASSWORD_OVERRIDE_"

    _lock = Lock()

    # External commands and formats
    bundle_cmds = {
        "cbz": "zip {name} {files}",
        "pdf": "convert -density 100 -units PixelsPerInch {name} {files}"
    }
    bundle_format = "cbz"
    converters = [
        ("ts", "mp4", "cat {input} > {output}", "rm {}"),
    ]
    anime_viewer = "mpv --sub-file-paths=\"$PWD\" --sub-auto=all --title={title} {media} "
    novel_viewer = "zathura {}"
    manga_viewer = "zathura {}"
    page_viewer = "sxiv {}"

    # HTTP related; Generally used as args to requests
    _verify = True
    bs4_parser = "html.parser"
    max_retires = 3
    status_to_retry = [429, 500, 502, 504]
    user_agent = "Mozilla/5.0"

    # Cookies
    cookie_files = ["/tmp/cookies.txt"]
    incapsula_prompt = ""
    js_enabled_browser = True

    # MISC
    allow_only_official_servers = False
    auto_upgrade_state = True
    free_only = False
    no_load_session = False
    no_save_session = False
    shell = True
    suppress_cmd_output = False
    threads = 8  # per server thread count

    # Server specific settings
    server_specific_settings = {}
    force_odd_pages = True
    auto_replace = True
    lang = ("en", "en-US", "English")

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
        self._translations = None

    def get_cookie_file(self):
        return os.path.join(self.cache_dir, "cookies.txt")

    def get_stats_file(self):
        return os.path.join(self.cache_dir, "stats.json")

    def get_translation_file(self):
        return os.path.join(self.config_dir, "translations.txt")

    def get_translations(self):
        with self._lock:
            if self._translations:
                return self._translations
            self._translations = []

            try:
                with open(self.get_translation_file(), 'r') as f:
                    for line in f:
                        line = line.strip()
                        if line and line[0] != "#":
                            if line.count("/") == 1:
                                src, target = line.split("/")
                            else:
                                _, src, target, _ = line.split("/")
                            self._translations.append((src, target))
            except FileNotFoundError:
                pass
        return self._translations

    def auto_replace_if_enabled(self, text, server_id=None):
        if self.get("auto_replace", server_id=server_id):
            for src, target in self.get_translations():
                text = re.sub(src, target, text)
        return text

    def get_cookie_files(self):
        yield self.get_cookie_file()
        yield from map(os.path.expanduser, self.cookie_files)

    def load_js_cookies(self, url, session):
        if self.js_enabled_browser:
            cookie_manager.update_session(url, session)
            return True
        return False

    @classmethod
    def get_members(clazz):
        return [attr for attr in dir(clazz) if not callable(getattr(clazz, attr)) and not attr.startswith("_")]

    def set(self, name, value, server_id=None):
        if isinstance(self.get(name), bool) and not isinstance(value, bool):
            value = value.lower() not in ["false", 0, ""]

        if isinstance(value, str) and (isinstance(self.get(name), int) or isinstance(value, float)):
            value = type(self.get(name))(value)
        if server_id:
            if not server_id in self.server_specific_settings:
                self.server_specific_settings[server_id] = {}
            self.server_specific_settings[server_id][name] = value
        else:
            setattr(self, name, value)
        return value

    def get(self, name, server_id=None):
        return getattr(self, name) if not server_id else self.server_specific_settings.get(server_id, {}).get(name, self.get(name))

    def save(self):
        with open(self.get_settings_file(), "w") as f:
            settings_to_save = {}
            members = Settings.get_members()
            for attr in members:
                settings_to_save[attr] = self.get(attr)
            json.dump(settings_to_save, f, indent=4)

    def load(self):
        try:
            with open(self.get_settings_file(), "r") as f:
                saved_settings = json.load(f)
                members = Settings.get_members()
                for attr in members:
                    if attr in saved_settings:
                        self.set(attr, saved_settings[attr])
        except FileNotFoundError:
            pass
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

    def get_incapsula(self, server_id: str) -> (str, str):
        output = subprocess.check_output(self.incapsula_prompt.format(server_id), shell=self.shell, stdin=subprocess.DEVNULL).strip().decode("utf-8")
        if output.startswith("incap_ses_"):
            return output.split("=", 1)
        else:
            return "incap_ses_979_998813", output

    def get_credentials(self, server_id: str) -> (str, str):
        """Returns the saved username, password"""
        if self.env_override_prefix:
            var = os.getenv(self.env_override_prefix + server_id) or os.getenv(self.env_override_prefix + server_id.upper())
            if var:
                return var.split(self.credential_separator)
        if self.password_manager_enabled and self.password_load_cmd:
            try:
                logging.debug("Loading credentials for %s `%s`", server_id, self.password_load_cmd.format(server_id))
                output = subprocess.check_output(self.password_load_cmd.format(server_id), shell=self.shell, stdin=subprocess.DEVNULL).strip().decode("utf-8")
                login, password = output.split(self.credential_separator)
                return login, password
            except subprocess.CalledProcessError:
                logging.info("Unable to load credentials for %s", server_id)

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

    def isVerifyingSSL(self):
        return self._verify

    def run_cmd(self, cmd, wd=None):
        subprocess.check_call(cmd, stdout=DEVNULL if self.suppress_cmd_output else None, shell=self.shell, cwd=wd) if isinstance(cmd, str) else cmd()

    def bundle(self, img_dirs):
        arg = " ".join(map(Settings._smart_quote, img_dirs))
        name = os.path.join(self.bundle_dir, "{}_{}.{}".format(datetime.now().strftime("%Y-%m-%d_%H:%M:%S"), str(hash(arg))[1:8], self.bundle_format))
        cmd = self.bundle_cmds[self.bundle_format].format(files=arg, name=name)
        logging.info("Running cmd %s shell = %s", cmd, self.shell)
        self.run_cmd(cmd)
        return name

    @staticmethod
    def _smart_quote(name):
        return quote(name) if name[-1] != "*" else quote(name[:-1]) + "*"

    def _open_viewer(self, viewer, name, title=None, wd=None):
        try:
            if isinstance(name, str):
                name = Settings._smart_quote(name)
            else:
                name = " ".join(map(Settings._smart_quote, name))
            cmd = viewer.format(media=name, title=quote(title)) if title else viewer.format(name)
            logging.info("Running cmd %s: %s shell = %s, wd=%s", viewer, cmd, self.shell, wd)
            self.run_cmd(cmd, wd=wd)
            return True
        except CalledProcessError:
            return False

    def open_manga_viewer(self, name):
        return self._open_viewer(self.manga_viewer, name)

    def open_anime_viewer(self, name, title, wd=None):
        return self._open_viewer(self.anime_viewer, name, title=title, wd=wd)

    def open_page_viewer(self, images):
        return self._open_viewer(self.page_viewer, images)

    def open_novel_viewer(self, file):
        return self._open_viewer(self.novel_viewer, file)

    def convert(self, extension, files, destWithoutExt):
        for ext, targetExt, cmd, cleanupCmd in self.converters:
            if ext == extension:
                targetFile = self._smart_quote(f"{destWithoutExt}.{targetExt}")
                logging.info("Converting %s to %s", files, targetFile)
                self.run_cmd(cmd.format(input=files, output=targetFile))
                self.run_cmd(cleanupCmd.format(files))

    def _getLanguage(self, server_id):
        return self.get("lang", server_id=server_id)

    def getLanguageCode(self, server_id):
        return self._getLanguage(server_id)[0]

    def getLanguageCountryCode(self, server_id):
        return self._getLanguage(server_id)[1]

    def getLanguageCountryCodeAlpha(self, server_id):
        return self.getLanguageCountryCode(server_id).replace("-", "")

    def getLanguageName(self, server_id):
        return self._getLanguage(server_id)[2]
