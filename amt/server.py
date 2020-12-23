import logging
import os
import time
from enum import Enum
from functools import lru_cache

import m3u8
from Crypto.Cipher import AES
from PIL import Image

from .job import Job

MANGA = 1
NOVEL = 2
ANIME = 4
NOT_ANIME = MANGA | NOVEL
ALL_MEDIA = NOT_ANIME | ANIME


class Server:
    id = None
    alias = None
    lang = 'en'
    locale = 'enUS'
    session = None
    settings = None
    media_type = MANGA
    external = False

    has_login = False
    has_gaps = False
    is_non_premium_account = False
    extension = "jpeg"

    def __init__(self, session, settings=None):
        self.settings = settings
        self.session = session

    def _request(self, get, url, **kwargs):
        logging.info("Making request to %s", url)
        r = self.session.get(url, **kwargs) if get else self.session.post(url, **kwargs)
        if r.status_code != 200:
            logging.warning(r)
        return r

    @lru_cache
    def session_get_cache(self, url):
        return self._request(True, url)

    def session_get(self, url, **kwargs):
        return self._request(True, url, **kwargs)

    def session_post(self, url, **kwargs):
        return self._request(False, url, **kwargs)

    def login(self, username, password):
        return False

    @lru_cache
    def relogin(self):
        credential = self.settings.get_credentials(self.id if not self.alias else self.alias)
        if credential:
            logged_in = self.login(credential[0], credential[1])
            if not logged_in:
                logging.warning("Could not login with username: %s", credential[0])
            return logged_in
        logging.warning("Could not load credentials")
        return False

    def get_media_list(self):
        """
        Returns full list of media sorted by rank
        """
        raise NotImplementedError

    def search(self, term):
        term_lower = term.lower()
        return list(filter(lambda x: term_lower in x['name'].lower(), self.get_media_list()))

    def update_media_data(self, media_data):
        """
        Returns media data from API

        Initial data should contain at least media's slug (provided by search)
        """
        raise NotImplementedError

    def get_media_chapter_data(self, media_data, chapter_data):
        raise NotImplementedError

    def save_chapter_page(self, page_data, path):
        raise NotImplementedError

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
        return self.has_login

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

    def _download_page(self, media_data, chapter_data, dir_path, index, page_data):
        temp_full_path = os.path.join(dir_path, Server.get_page_name_from_index(index) + "-temp." + page_data["ext"])
        full_path = os.path.join(dir_path, Server.get_page_name_from_index(index) + "." + page_data["ext"])

        logging.warning("downloading %s", full_path)
        if os.path.exists(full_path):
            logging.debug("Page %s already download", full_path)
        else:
            self.save_chapter_page(page_data, temp_full_path)
            os.rename(temp_full_path, full_path)
            downloaded_page = True

    def download_chapter(self, media_data, chapter_data, page_limit=None):
        if self.is_fully_downloaded(media_data, chapter_data):
            logging.info("Already downloaded of %s %s", media_data["name"], chapter_data["title"])
            return True, False

        logging.info("Starting download of %s %s", media_data["name"], chapter_data["title"])
        if chapter_data["premium"]:
            if not self.is_non_premium_account and self.needs_authentication():
                logging.info("Server is not authenticated; relogging in")
                if not self.relogin():
                    logging.info("Cannot access chapter %s #%s %s", media_data["name"], str(chapter_data["number"]), chapter_data["title"])
                    return False, False
            if self.is_non_premium_account:
                logging.info("Cannot access chapter %s #%s %s because account is not premium", media_data["name"], str(chapter_data["number"]), chapter_data["title"])
                return False, False

        list_of_pages = self.get_media_chapter_data(media_data, chapter_data)
        assert list_of_pages

        logging.info("Downloading %d pages", len(list_of_pages))
        downloaded_page = False

        dir_path = self._get_dir(media_data, chapter_data)
        job = Job(self.settings.threads)
        for index, page_data in enumerate(list_of_pages[:page_limit]):
            job.add(lambda index=index, page_data=page_data: self._download_page(media_data, chapter_data, dir_path, index, page_data))
        job.run()

        if self.settings.force_odd_pages and self.media_type == MANGA and len(list_of_pages[:page_limit]) % 2:
            full_path = os.path.join(dir_path, Server.get_page_name_from_index(len(list_of_pages[:page_limit])) + ".jpeg")
            image = Image.new('RGB', (100, 100))
            image.save(full_path, "jpeg")

        self.mark_download_complete(dir_path)
        logging.info("%s %d %s is downloaded", media_data["name"], chapter_data["number"], chapter_data["title"])

        return True, True

    def get_stream_data(self, media_data, chapter_data):
        assert media_data["media_type"] == ANIME
        m3u8_url = self.get_stream_url(chapter_data=chapter_data)
        return [self.create_page_data(url=segment.uri, encryption_key=segment.key) for segment in m3u8.load(m3u8_url).segments]

    def save_stream(self, page_data, path):
        r = self.session_get(page_data["url"])
        content = r.content
        key = page_data["encryption_key"]
        if key:
            key_bytes = self.session_get_cache(page_data["encryption_key"].uri).content
            content = AES.new(key_bytes, AES.MODE_CBC, key.iv).decrypt(content)
        with open(path, 'wb') as fp:
            fp.write(content)

    def is_url_for_known_media(self, url, known_media):
        return False

    def can_stream_url(self, url):
        return False

    def get_stream_url(self, media_data=None, chapter_data=None, url=None, raw=False):
        return False

    def get_media_data_from_url(self, url):
        raise NotImplementedError

    def get_media_title(self, media_data, chapter):
        return "{}: #{} {}".format(media_data["name"], chapter["number"], chapter["title"])

    def create_media_data(self, id, name, season_ids=None, season_number="", media_type=None, dir_name=None, offset=0, cover=None):
        return dict(server_id=self.id, id=id, dir_name=dir_name if dir_name else name.replace(" ", "_"), name=name, media_type=media_type or self.media_type, cover=None, progress=0, season_ids=season_ids, season_number=season_number, offset=offset, chapters={})

    def update_chapter_data(self, media_data, id, title, number, premium=False, special=False, date=None):
        id = str(id)
        if isinstance(number, str):
            if number.isalpha():
                logging.info("Chapter number %s is not valid; skipping", number)
                return False
            try:
                number = int(number)
            except ValueError:
                special = True
                number = float(number.replace("-", "."))
        if media_data["offset"]:
            number -= media_data["offset"]
        if number % 1 == 0:
            number = int(number)

        new_values = dict(id=id, title=title, number=number, premium=premium, special=special, date=date)
        if id in media_data["chapters"]:
            media_data["chapters"][id].update(new_values)
        else:
            media_data["chapters"][id] = new_values
            media_data["chapters"][id]["read"] = False
        return True

    def create_page_data(self, url, id=None, encryption_key=None, ext=None):
        assert url
        return dict(url=url, id=id, encryption_key=encryption_key, ext=ext or self.extension)
