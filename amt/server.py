import logging
import os
import time
from enum import Enum
from functools import lru_cache
from shlex import quote

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
        logging.info(url)
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

    @staticmethod
    def mark_download_complete(dir_path):
        full_path = os.path.join(dir_path, Server.get_download_marker())
        open(full_path, 'w').close()

    def _get_dir(self, media_data, chapter_data):
        return self.settings.get_chapter_dir(media_data, chapter_data)

    def is_fully_downloaded(self, media_data, chapter_data):
        dir_path = self._get_dir(media_data, chapter_data)
        full_path = os.path.join(dir_path, self.get_download_marker())
        return os.path.exists(full_path)

    def get_children(self, media_data, chapter_data):
        return "{}/*".format(quote(self._get_dir(media_data, chapter_data)))

    def download_chapter(self, media_data, chapter_data, page_limit=None):
        if self.is_fully_downloaded(media_data, chapter_data):
            logging.debug("Already downloaded of %s %s", media_data["name"], chapter_data["title"])
            return True, False

        logging.info("Starting download of %s %s", media_data["name"], chapter_data["title"])
        if chapter_data["premium"]:
            if not self.is_non_premium_account and self.needs_authentication():
                logging.debug("Server is not authenticated; relogging in")
                if not self.relogin():
                    logging.info("Cannot access chapter %s #%s %s", media_data["name"], str(chapter_data["number"]), chapter_data["title"])
                    return False, False
            if self.is_non_premium_account:
                logging.info("Cannot access chapter %s #%s %s because account is not premium", media_data["name"], str(chapter_data["number"]), chapter_data["title"])
                return False, False

        list_of_pages = self.get_media_chapter_data(media_data, chapter_data)
        logging.debug("Starting download for %d pages", len(list_of_pages))
        downloaded_page = False

        dir_path = self._get_dir(media_data, chapter_data)
        for index, page_data in enumerate(list_of_pages[:page_limit]):
            temp_full_path = os.path.join(dir_path, Server.get_page_name_from_index(index) + "-temp." + self.extension)
            full_path = os.path.join(dir_path, Server.get_page_name_from_index(index) + "." + self.extension)

            if os.path.exists(full_path):
                logging.debug("Page %s already download", full_path)
            else:
                self.save_chapter_page(page_data, temp_full_path)
                os.rename(temp_full_path, full_path)
                downloaded_page = True
        Server.mark_download_complete(dir_path)
        logging.info("%s %d %s is downloaded", media_data["name"], chapter_data["number"], chapter_data["title"])

        return True, downloaded_page

    def get_media_chapter_data(self, media_data, chapter_data):
        """
        Returns media chapter data

        Currently, only pages are expected.
        """
        raise NotImplementedError

    def save_chapter_page(self, page_data, path):
        """
        Returns chapter page scan (image) content
        """
        raise NotImplementedError

    def is_url_for_known_media(self, url, known_media):
        return False

    def can_stream_url(self, url):
        return False

    def get_stream_url(self, media_id=None, chapter_id=None, url=None):
        return False

    def get_media_data_from_url(self, url):
        raise NotImplementedError

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

    def create_page_data(self, url, id=None, encryption_key=None):
        return dict(url=url, id=id, encryption_key=encryption_key)
