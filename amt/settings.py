import getpass
import logging
import os
import re
import subprocess

from shlex import quote
from subprocess import CalledProcessError
from threading import Lock

from .util.media_type import MediaType

APP_NAME = "amt"


class Settings:

    _lock = Lock()

    # env
    allow_env_override = True
    env_override_prefix = "AMT_"

    # Password manager related settings
    password_manager_enabled = True
    password_save_cmd = "{ echo {username}; cat - } | tpm insert {server_id}"
    password_load_cmd = "tpm show {server_id}"
    credential_separator_regex = r"[\t|\n]+"
    password_override_prefix = "PASSWORD_OVERRIDE_"

    # HTTP related; Generally used as args to requests
    bs4_parser = "html.parser"
    max_retries = 3
    backoff_factor = 1.0
    status_to_retry = [429, 500, 502, 503, 504]
    user_agent = "Mozilla/5.0"

    # Cookies
    cookie_files = ["/tmp/cookies.txt"]  # Additional cookies files to read from (Read only)

    # Servers/Tracker
    enabled_servers = []  # empty means all servers all enabled
    disabled_servers = []  # empty means all servers all enabled
    tracker_id = ""

    # MISC
    allow_only_official_servers = False
    no_load_session = False
    no_save_session = False
    shell = True
    subtitles_dir = ".subtitles/"

    # Server or media specific settings
    # Any keys defined in this dict should be declared in the class
    _specific_settings = {
        "preferred_primary_language": {
            MediaType.ANIME.name: ["JP", "JAPANESE", ""]
        },
        "viewer": {
            MediaType.ANIME.name: "mpv --merge-files --sub-file-paths=\"$PWD/.subtitles\" --sub-auto=all --title={title} {media}",
            MediaType.MANGA.name: "sxiv {media}",
            MediaType.NOVEL.name: "zathura {media}"
        }
    }

    bundle_cmd = "zip {name} {files}"
    bundle_format = "{date}_{name}.cbz"
    bundle_viewer = "zathura {media}"
    chapter_dir_name_format = "{chapter_number:06.1f}"
    chapter_page_format = "{page_number:04d}.{ext}"
    chapter_title_format = "{media_name}: #{chapter_number} {chapter_title}"
    special_chapter_dir_name_format = "{chapter_id}"
    disable_ssl_verification = False
    download_torrent_cmd = ""
    keep_unavailable = False
    post_process_cmd = ""
    text_languages = ["en", "en-US", "English"]
    preferred_primary_language = ["EN", "EN-US", "ENGLISH", ""]
    threads = 8  # per server thread count
    viewer = ""
    tmp_dir = "/tmp/.amt"

    def __init__(self, no_save_session=False, no_load=False, skip_env_override=False):
        home = os.getenv("AMT_HOME", os.getenv("HOME"))
        self.config_dir = os.path.join(os.getenv("XDG_CONFIG_HOME", os.path.join(home, ".config")), APP_NAME)
        self.cache_dir = os.path.join(os.getenv("XDG_CACHE_HOME", os.path.join(home, ".cache")), APP_NAME)
        self.data_dir = os.path.join(os.getenv("XDG_DATA_HOME", os.path.join(home, ".local/share")), APP_NAME)
        self.set_data_dirs(self.data_dir)

        self.no_save_session = no_save_session
        if not no_load:
            self.load(skip_env_override=skip_env_override)

    def set_tmp_dir(self):
        self.set_data_dirs(self.tmp_dir)

    def set_data_dirs(self, data_dir=None):
        self.bundle_dir = os.path.join(data_dir, "Bundles")
        self.media_dir = os.path.join(data_dir, "Media")
        self.external_downloads_dir = os.path.join(data_dir, "Torrents")

    def get_bundle_metadata_file(self):
        return os.path.join(self.data_dir, "bundles.json")

    def get_server_cache_file(self):
        return os.path.join(self.cache_dir, "server_cache.json")

    def get_cookie_file(self):
        return os.path.join(self.cache_dir, "cookies.txt")

    def get_cookie_files(self):
        yield self.get_cookie_file()
        yield from map(os.path.expanduser, self.cookie_files)

    def get_metadata_file(self):
        return os.path.join(self.data_dir, "metadata.json")

    def get_remote_servers_config_file(self):
        return os.path.join(self.config_dir, "remote_servers.conf")

    def get_settings_file(self):
        return os.path.join(self.config_dir, "amt.conf")

    def get_stats_file(self):
        return os.path.join(self.cache_dir, "stats.json")

    def get_web_cache(self, url):
        return os.path.join(self.cache_dir, url.replace("/", "_"))

    @classmethod
    def get_members(clazz):
        return [attr for attr in dir(clazz) if not callable(getattr(clazz, attr)) and not attr.startswith("_")]

    def __getattr__(self, key):
        if key.startswith("get_"):
            key = key[len("get_"):]
            return lambda x: self.get_field(key, x)

    def set_field(self, name, value, server_or_media_id=None):
        assert value is not None
        assert name in Settings.get_members()
        current_field = self.get_field(name, server_or_media_id)
        if isinstance(current_field, bool) and isinstance(value, str):
            value = value.lower() not in ["false", 0, ""]
        if isinstance(current_field, list) and isinstance(value, str):
            value = value.split(",") if value else []
            if current_field:
                value = list(map(lambda x: type(current_field[0])(x.strip()), value))

        if value and isinstance(value, str) and ((isinstance(current_field, int) or isinstance(current_field, float))):
            value = type(current_field)(value)
        if server_or_media_id:
            if not name in self._specific_settings:
                self._specific_settings[name] = {}
            self._specific_settings[name][server_or_media_id] = value
        else:
            setattr(self, name, value)
        return value

    def get_field(self, name, media_data=None):
        for key in media_data.get_labels() if isinstance(media_data, dict) else [media_data] if isinstance(media_data, (str, int)) or not media_data else [media_data.id, media_data.media_type.name]:
            if name in self._specific_settings and key in self._specific_settings[name]:
                return self._specific_settings[name][key]
        return getattr(self, name)

    def get_field_as_string(self, name, media_data=None):
        f = self.get_field(name, media_data)
        return f if not isinstance(f, list) else ",".join(map(str, f))

    def save(self):
        os.makedirs(self.config_dir, exist_ok=True)
        with open(self.get_settings_file(), "w") as f:
            for name in sorted(Settings.get_members()):
                f.write(f"{name}={self.get_field_as_string(name)}\n")
                for slug in self._specific_settings.get(name, {}):
                    f.write(f"{name}.{slug}={self.get_field_as_string(name, slug)}\n")

    def load(self, skip_env_override=False):
        try:
            with open(self.get_settings_file(), "r") as f:
                for line in filter(lambda x: x.strip() and x.strip()[0] != "#", f):
                    name, value = (line if not line.endswith("\n") else line[:-1]).split("=", 1)
                    attr, slug = name.split(".", 2) if "." in name else (name, None)
                    self.set_field(attr, value, slug)
        except FileNotFoundError:
            pass
        if not skip_env_override and self.allow_env_override:
            for attr in Settings.get_members():
                env_value = os.getenv(f"{self.env_override_prefix}{attr.upper()}")
                if env_value is not None:
                    self.set_field(attr, env_value)
                if attr in self._specific_settings:
                    for key in self._specific_settings.get(attr):
                        env_value = os.getenv(f"{self.env_override_prefix}{attr.upper()}_{key}")
                        if env_value is not None:
                            self.set_field(attr, env_value, key)

        os.environ["USER_AGENT"] = self.user_agent

    def get_external_downloads_dir(self, mediaType, skip_auto_create=False):
        path = os.path.join(self.external_downloads_dir, mediaType.name)
        if not skip_auto_create:
            os.makedirs(path, exist_ok=True)
        return path

    def get_external_downloads_path(self, media_data):
        return os.path.join(self.get_external_downloads_dir(MediaType(media_data["media_type"])), media_data["id"] + ".torrent")

    def get_chapter_metadata_file(self, media_data):
        return os.path.join(self.get_media_dir(media_data), "chapter_metadata.json")

    def get_server_dir(self, server_id):
        return os.path.join(self.media_dir, server_id)

    def get_media_dir(self, media_data):
        return os.path.join(self.get_server_dir(media_data["server_id"]), media_data["dir_name"])

    def get_chapter_dir(self, media_data, chapter_data, skip_create=False):
        fmt_str = (self.get_special_chapter_dir_name_format if chapter_data["special"] else self.get_chapter_dir_name_format)(media_data)
        chapter_dir_name = fmt_str.format(media_name=media_data["name"], chapter_number=chapter_data["number"], chapter_title=chapter_data["title"], chapter_id=chapter_data["id"])
        chapter_path = os.path.join(self.get_media_dir(media_data), chapter_dir_name)
        if not skip_create:
            os.makedirs(chapter_path, exist_ok=True)
        return chapter_path

    def get_page_file_name(self, media_data, chapter_data, ext, page_number=0):
        return self.get_chapter_page_format(media_data).format(media_name=media_data["name"], chapter_number=chapter_data["number"], chapter_title=chapter_data["title"], page_number=page_number, ext=ext)

    def is_server_enabled(self, server_id, is_offical=True):
        if self.allow_only_official_servers and not is_offical:
            return False
        return server_id in self.enabled_servers + [self.tracker_id] if self.enabled_servers else server_id not in self.disabled_servers and server_id

    def is_allowed_text_lang(self, lang, media_data):
        return lang in self.get_field("text_languages", media_data)

    def get_prefered_lang_key(self, media_data, lang=None):
        try:
            return self.get_field("preferred_primary_language", media_data).index((lang or media_data.get("lang", "")).upper())
        except ValueError:
            return float("inf")

    def get_prompt_for_input(self, prompt):
        return input(prompt)

    def _ask_for_credentials(self, server_id: str) -> (str, str):
        if self.password_manager_enabled and self.password_load_cmd:
            try:
                logging.debug("Loading credentials for %s `%s`", server_id, self.password_load_cmd.format(server_id=server_id))
                output = subprocess.check_output(self.password_load_cmd.format(server_id=server_id), shell=self.shell).decode("utf-8")
                login, password = re.split(self.credential_separator_regex, output)[:2]
                return login, password
            except (CalledProcessError, ValueError):
                logging.error("Unable to load credentials for %s", server_id)
                raise
        else:
            return input("Username: "), getpass.getpass()

    def get_credentials(self, server_id: str) -> (str, str):
        """Returns the saved username, password"""
        if self.password_override_prefix:
            var = os.getenv(self.password_override_prefix + server_id) or os.getenv(self.password_override_prefix + server_id.upper())
            if var:
                return re.split(self.credential_separator_regex, var)
        with self._lock:
            return self._ask_for_credentials(server_id)

    def store_credentials(self, server_id, username, password=None):
        """Stores the username, password for the given server_id"""
        if password is None:
            password = getpass.getpass()
        if self.password_manager_enabled and self.password_save_cmd:
            cmd = self.password_save_cmd.format(server_id=server_id, username=username)
            logging.debug("Storing credentials for %s; cmd %s", server_id, cmd)
            subprocess.check_output(cmd, shell=self.shell, input=bytes(password, "utf8"))

    def get_secret(self, server_id: str) -> (str, str):
        result = self.get_credentials(server_id)
        return result[0] or result[1] if result else None

    def store_secret(self, server_id, secret):
        self.store_credentials(server_id, "", secret)

    def run_cmd(self, cmd, wd=None):
        logging.info("Running cmd %s: shell = %s, wd=%s", cmd, self.shell, wd)
        subprocess.check_call(cmd, shell=self.shell, cwd=wd) if isinstance(cmd, str) else cmd()

    @staticmethod
    def _smart_quote(name):
        return quote(name) if name[-1] != "*" else quote(name[:-1]) + "*"

    def _open_viewer(self, viewer, name, title, wd=None):
        try:
            assert isinstance(name, str)
            name = Settings._smart_quote(name)
            cmd = viewer.format(media=name, title=quote(title)) if title else viewer.format(name)
            self.run_cmd(cmd, wd=wd)
            return True
        except (CalledProcessError, KeyboardInterrupt):
            return False

    def open_viewer(self, files, media_data, chapter_data, wd=None):
        viewer = self.get_field("viewer", media_data)
        title = self.get_field("chapter_title_format", media_data).format(media_name=media_data["name"], chapter_number=chapter_data["number"], chapter_title=chapter_data["title"])
        if wd is None:
            wd = self.get_chapter_dir(media_data, chapter_data)
        return self._open_viewer(viewer, files, title=title, wd=wd)

    def open_bundle_viewer(self, bundle_name, media_data=None):
        viewer = self.get_field("bundle_viewer", media_data)
        return self._open_viewer(viewer, os.path.join(self.bundle_dir, bundle_name), title=bundle_name)

    def bundle(self, img_dirs, name=None, media_data=None):
        from datetime import datetime
        os.makedirs(self.bundle_dir, exist_ok=True)
        arg = " ".join(map(Settings._smart_quote, img_dirs))
        count = 0
        name = name if name else "ALL"
        while True:
            bundle_name = self.get_bundle_format(media_data).format(date=datetime.now().strftime("%Y-%m-%d"), name=name + str(count) if count else name)
            bundle_path = os.path.join(self.bundle_dir, bundle_name)
            if os.path.exists(bundle_path):
                count += 1
                continue
            cmd = self.bundle_cmd.format(files=arg, name=bundle_path)
            self.run_cmd(cmd)
            return bundle_name

    def post_process(self, media_data, file_paths, dir_path):
        cmd = self.get_field("post_process_cmd", media_data)
        if cmd:
            self.run_cmd(cmd.format(files=" ".join(map(Settings._smart_quote, file_paths)), wd=dir_path))

    def start_torrent_download(self, media_data):
        cmd = self.get_field("download_torrent_cmd", media_data)
        file = self.get_external_downloads_path(media_data)
        self.run_cmd(cmd.format(media_id=media_data["id"], torrent_file=file), wd=os.path.dirname(file))
