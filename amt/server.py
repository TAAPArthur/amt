import logging
import os
import re
import time
from functools import cache
from threading import Lock

import m3u8
from Crypto.Cipher import AES
from PIL import Image
from requests.exceptions import HTTPError

from .job import Job

MANGA = 1
NOVEL = 2
ANIME = 4
NOT_ANIME = MANGA | NOVEL
ALL_MEDIA = NOT_ANIME | ANIME
MEDIA_TYPES = {"MANGA": MANGA, "NOVEL": NOVEL, "ANIME": ANIME}


class Server:
    id = None
    alias = None
    domain = None
    lang = 'en'
    locale = 'enUS'
    session = None
    settings = None
    media_type = MANGA
    external = False
    is_protected = False

    has_login = False
    has_gaps = False
    is_non_premium_account = False
    is_premium = False
    is_logged_in = False
    stream_url_regex = None

    # progress in chapters (default) or volumes
    progress_in_volumes = False

    extension = "jpeg"
    incapsula_flag = "Request unsuccessful. Incapsula incident ID:"
    incapsula_regex = re.compile(r"/_Incapsula_Resource\?SWJIYLWA=[0-9a-z]*,[0-9a-z]*")

    def __init__(self, session, settings=None):
        self.settings = settings
        self.session = session
        self._lock = Lock()

    @property
    def lock(self):
        return self._lock

    def _request(self, get, url, **kwargs):
        logging.info("Making request to %s", url)
        logging.debug("Request args: %s ", kwargs)
        kwargs["verify"] = self.settings.isVerifyingSSL()
        r = self.session.get(url, **kwargs) if get else self.session.post(url, **kwargs)
        if r.status_code != 200:
            logging.warning("HTTP Error: %d %s", r.status_code, r.text)
        r.raise_for_status()
        return r

    def _request_or_prompt_incapsula(self, url, no_load_cookies=False, **kwargs):
        r = self.session_get(url, **kwargs)
        for i in range(self.settings.max_retires):
            if (self.incapsula_flag in r.text or self.incapsula_regex.search(r.text)):
                time.sleep(1)
                if self.settings.incapsula_prompt:
                    logging.info("Detected _Incapsula_Resource")
                    name, value = self.settings.get_incapsula(self.id)
                    self.session.cookies.set(name, value, domain=self.domain, path="/")
                r = self._request(True, url)
        if self.incapsula_flag in r.text or self.incapsula_regex.search(r.text):
            if not no_load_cookies and self.settings.load_js_cookies(url, self.session):
                return self._request_or_prompt_incapsula(url, True, **kwargs)
            raise ValueError(r.text[-500:])
        return r

    def add_cookie(self, name, value, domain=None, path="/"):
        self.session.cookies.set(name, value, domain=domain or self.domain, path=path)

    def session_get_cache(self, url, **kwargs):
        return self.settings.get_cache(url, lambda: self._request_or_prompt_incapsula(url, **kwargs))

    def session_get_protected(self, url, **kwargs):
        return self._request_or_prompt_incapsula(url, **kwargs)

    @cache
    def session_get_mem_cache(self, url, **kwargs):
        return self._request_or_prompt_incapsula(url, **kwargs)

    def session_get(self, url, **kwargs):
        return self._request(True, url, **kwargs)

    def session_post(self, url, **kwargs):
        return self._request(False, url, **kwargs)

    def login(self, username, password):
        return False

    def relogin(self):
        if self.is_logged_in:
            return True
        credential = self.settings.get_credentials(self.id if not self.alias else self.alias)
        if credential:
            try:
                logged_in = self.login(credential[0], credential[1])
            except:
                logged_in = False
            if not logged_in:
                logging.warning("Could not login with username: %s", credential[0])
            else:
                logging.info("Logged into %s; premium %s", self.id, self.is_premium)

            self.is_logged_in = logged_in
            return logged_in
        logging.warning("Could not load credentials")
        return False

    def get_media_list(self):
        """
        Returns an arbitrary selection of media; Used solely for tests
        """
        return self.search("One")

    def search(self, term):
        """
        Searches for a media containing term
        Different servers will handle search differently. Some are very literal while others do prefix matching and some would match any word
        """
        term_lower = term.lower()
        return list(filter(lambda x: term_lower in x['name'].lower(), self.get_media_list()))

    def update_media_data(self, media_data):
        """
        Returns media data from API

        Initial data should contain at least media's slug (provided by search)
        """
        raise NotImplementedError

    def get_media_chapter_data(self, media_data, chapter_data):
        """
        Returns a list of page/episode data. For anime (specifically for video files) this may be a list of size 1
        The default implementation is for anime servers and will contain the preferred stream url
        """
        return [self.create_page_data(url=self.get_stream_url(media_data, chapter_data), ext=self.extension)]

    def get_stream_data(self, media_data, chapter_data):
        assert media_data["media_type"] == ANIME
        m3u8_url = self.get_stream_url(media_data=media_data, chapter_data=chapter_data)
        return [self.create_page_data(url=segment.uri, encryption_key=segment.key) for segment in m3u8.load(m3u8_url).segments]

    def get_chapter_id_for_url(self, url):
        return None

    def can_stream_url(self, url):
        return self.stream_url_regex and self.stream_url_regex.match(url)

    def get_stream_url(self, media_data, chapter_data, quality=0):
        return list(self.get_stream_urls(media_data=media_data, chapter_data=chapter_data))[quality]

    def get_stream_urls(self, media_data=None, chapter_data=None, url=None):
        return []

    def get_media_data_from_url(self, url):
        raise NotImplementedError

    def save_chapter_page(self, page_data, path):
        r = self.session_get(page_data["url"], stream=True)
        content = r.content
        key = page_data["encryption_key"]
        if key:
            key_bytes = self.session_get_mem_cache(key.uri).content
            content = AES.new(key_bytes, AES.MODE_CBC, key.iv).decrypt(content)
        with open(path, 'wb') as fp:
            fp.write(content)

    @staticmethod
    def get_page_name_from_index(page_index):
        return '%04d' % page_index

    def needs_authentication(self):
        """
        Checks if the user is logged in
        If the user is logged into a non-premium account,
        is_non_premium_account should be set to False

        If the user is not logged in (and needs to login to access all content),
        this method should return true.
        """
        return self.has_login and not self.is_logged_in

    @staticmethod
    def get_download_marker():
        return ".downloaded"

    def mark_download_complete(self, dir_path):
        full_path = os.path.join(dir_path, Server.get_download_marker())
        open(full_path, 'w').close()

    def _get_dir(self, media_data, chapter_data):
        return self.settings.get_chapter_dir(media_data, chapter_data)

    def is_fully_downloaded(self, media_data, chapter_data):
        dir_path = self._get_dir(media_data, chapter_data)
        full_path = os.path.join(dir_path, self.get_download_marker())
        return os.path.exists(full_path)

    def get_children(self, media_data, chapter_data):
        return "{}/*".format(self._get_dir(media_data, chapter_data))

    def download_if_missing(self, func, full_path):
        logging.info("downloading %s", full_path)
        if os.path.exists(full_path):
            logging.debug("Page %s already download", full_path)
        else:
            temp_path = os.path.join(os.path.dirname(full_path), ".tmp-" + os.path.basename(full_path))
            func(temp_path)
            os.rename(temp_path, full_path)

    def _get_page_path(self, media_data, chapter_data, dir_path, index, page_data):
        return os.path.join(dir_path, Server.get_page_name_from_index(index) + "." + page_data["ext"])

    def download_subtitles(self, media_data, chapter_data, dir_path):
        pass

    def post_download(self, media_data, chapter_data, dir_path):
        pass

    def needs_to_login(self):
        try:
            return not self.is_logged_in and self.needs_authentication()
        except HTTPError:
            return True

    def pre_download(self, media_data, chapter_data, dir_path):
        if chapter_data["premium"] and not self.is_premium:
            if self.needs_to_login():
                logging.info("Server is not authenticated; relogging in")
                if not self.relogin():
                    logging.info("Cannot access chapter %s #%s %s", media_data["name"], str(chapter_data["number"]), chapter_data["title"])
            else:
                self.is_logged_in = True
            if not self.is_premium:
                logging.info("Cannot access chapter %s #%s %s because account is not premium", media_data["name"], str(chapter_data["number"]), chapter_data["title"])
                raise ValueError("Cannot access premium chapter")
        self.download_subtitles(media_data, chapter_data, dir_path=dir_path)

    def download_chapter(self, media_data, chapter_data, page_limit=None):
        if self.is_fully_downloaded(media_data, chapter_data):
            logging.info("Already downloaded %s %s", media_data["name"], chapter_data["title"])
            return False

        logging.info("Starting download of %s %s", media_data["name"], chapter_data["title"])
        dir_path = self._get_dir(media_data, chapter_data)
        os.makedirs(dir_path, exist_ok=True)
        self.lock.acquire()
        try:
            self.pre_download(media_data, chapter_data, dir_path)
            list_of_pages = self.get_media_chapter_data(media_data, chapter_data)
            assert list_of_pages
            logging.info("Downloading %d pages", len(list_of_pages))

            job = Job(self.settings.threads, raiseException=True)
            for index, page_data in enumerate(list_of_pages[:page_limit]):
                full_path = self._get_page_path(media_data, chapter_data, dir_path, index, page_data)
                job.add(lambda path=full_path, page_data=page_data: self.download_if_missing(lambda x: self.save_chapter_page(page_data, x), path))
            job.run()

            if self.settings.force_odd_pages and self.media_type == MANGA and len(list_of_pages[:page_limit]) % 2:
                full_path = os.path.join(dir_path, Server.get_page_name_from_index(len(list_of_pages[:page_limit])) + ".jpeg")
                image = Image.new('RGB', (100, 100))
                image.save(full_path, "jpeg")

            self.post_download(media_data, chapter_data, dir_path)
            self.mark_download_complete(dir_path)
            logging.info("%s %d %s is downloaded", media_data["name"], chapter_data["number"], chapter_data["title"])
        finally:
            self.lock.release()

        return True

    def get_media_title(self, media_data, chapter):
        return "{}: #{} {}".format(media_data["name"], chapter["number"], chapter["title"])

    def create_media_data(self, id, name, season_id=None, season_title="", media_type=None, dir_name=None, offset=0, alt_id=None, cover=None, progress_in_volumes=False):
        return dict(server_id=self.id, id=id, dir_name=dir_name if dir_name else re.sub(r"[\W]", "", name.replace(" ", "_")), name=name, media_type=media_type or self.media_type, cover=None, progress=0, season_id=season_id, season_title=season_title, offset=offset, chapters={}, alt_id=alt_id, trackers={}, progress_in_volumes=progress_in_volumes)

    def update_chapter_data(self, media_data, id, title, number, premium=False, alt_id=None, special=False, date=None, subtitles=None):
        id = str(id)
        if isinstance(number, str):
            if not number or number.isalpha():
                logging.info("Chapter number %s is not valid; skipping", number)
                return False
            try:
                number = int(number)
            except ValueError:
                special = True
                number = float(number.replace("-", "."))
        elif number is None:
            number = 0
        if number % 1 == 0:
            number = int(number)
        if media_data["offset"]:
            number -= media_data["offset"]
            if number % 1 != 0:
                number = round(number, 4)

        new_values = dict(id=id, title=title, number=number, premium=premium, alt_id=alt_id, special=special, date=date, subtitles=subtitles)
        if id in media_data["chapters"]:
            media_data["chapters"][id].update(new_values)
        else:
            media_data["chapters"][id] = new_values
            media_data["chapters"][id]["read"] = False
        return True

    def create_page_data(self, url, id=None, encryption_key=None, ext=None):
        if not ext:
            _, ext = os.path.splitext(url.split("?")[0])
            if ext and ext[0] == ".":
                ext = ext[1:]
        return dict(url=url, id=id, encryption_key=encryption_key, ext=ext or self.extension)
