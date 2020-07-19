import requests_cache
import os
import logging
import time


class Server:
    enabled = True
    id = None
    lang = 'en'
    locale = 'enUS'
    session = None
    settings = None
    dirty = False

    static_pages = False
    has_anime = False
    has_manga = True
    has_login = False
    has_free_chapters = True

    def __init__(self, session, settings=None):
        self.settings = settings
        self.session = session

    def is_session_dirty(self):
        return self.dirty

    def set_session_dirty(self, value=True):
        self.dirty = value

    def login(self, username, password):
        return False

    def relogin(self):
        credential = self.settings.get_credentials(self.id)
        if credential:
            logged_in = self.login(credential[0], credential[1])
            if not logged_in:
                logging.warning("Could not login with username: %s", credential[0])
            return logged_in
        logging.warning("Could not load credentials")
        return False

    def get_manga_list(self):
        """
        Returns full list of manga sorted by rank
        """
        raise NotImplementedError

    def search(self, term):
        term_lower = term.lower()
        return list(filter(lambda x: term_lower in x['name'].lower(), self.get_manga_list()))

    def update_manga_data(self, manga_data):
        """
        Returns manga data from API

        Initial data should contain at least manga's slug (provided by search)
        """
        raise NotImplementedError

    @staticmethod
    def get_page_name_from_index(page_index):
        return '%03d' % page_index

    def needs_authenticated(self):
        return self.has_login

    def download_chapter(self, manga_data, chapter_data, page_limit=None):
        if not self.static_pages:
            with self.session.cache_disabled():
                return self._download_chapter(manga_data, chapter_data, page_limit)
        else:
            return self._download_chapter(manga_data, chapter_data, page_limit)

    def _download_chapter(self, manga_data, chapter_data, page_limit=None):
        logging.info("Starting download of %s %s", manga_data["name"], chapter_data["title"])
        if chapter_data["premium"] and self.needs_authenticated():
            logging.debug("Server is not authenticated; relogging in")
            if not self.relogin():
                logging.info("Cannot access chapter %s #%f %s", manga_data["name"], chapter_data["number"], chapter_data["title"])
                return False
        list_of_pages = self.get_manga_chapter_data(manga_data, chapter_data)
        dir_path = self.settings.get_chapter_dir(manga_data, chapter_data)
        logging.debug("Starting download for %d pages", len(list_of_pages))
        downloaded_page = False
        for index, page_data in enumerate(list_of_pages[:page_limit]):
            temp_full_path = os.path.join(dir_path, Server.get_page_name_from_index(index) + "-temp.png")
            full_path = os.path.join(dir_path, Server.get_page_name_from_index(index) + ".png")

            if os.path.exists(full_path):
                logging.debug("Page %s already download", full_path)
            else:
                self.save_chapter_page(page_data, temp_full_path)
                os.rename(temp_full_path, full_path)
                downloaded_page = True
        logging.info("%s %d %s is downloaded", manga_data["name"], chapter_data["number"], chapter_data["title"])
        return downloaded_page

    def get_manga_chapter_data(self, manga_data, chapter_data):
        """
        Returns manga chapter data

        Currently, only pages are expected.
        """
        raise NotImplementedError

    def save_chapter_page(self, page_data, path):
        """
        Returns chapter page scan (image) content
        """
        raise NotImplementedError

    def create_manga_data(self, id, name, cover=None):
        return dict(server_id=self.id, id=id, name=name, cover=None, progress=0, chapters={}, trackers={}, tracker_lists={})

    def update_chapter_data(self, manga_data, id, title, number, premium=False, read=False, incomplete=False, date=None):
        id = str(id)
        special = False
        try:
            number = int(number)
        except ValueError:
            special = True
            number = float(number.replace("-", "."))

        new_values = dict(id=id, title=title, number=number, premium=premium, read=read, incomplete=False, special=special, data=date)
        if id in manga_data["chapters"]:
            manga_data["chapters"][id].update(new_values)
        else:
            manga_data["chapters"][id] = new_values

    def create_page_data(self, url, id=None, encryption_key=None):
        return dict(url=url, id=id, encryption_key=encryption_key)
