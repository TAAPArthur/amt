import requests_cache
import os
from cachecontrol import CacheControl
from cachecontrol.caches.file_cache import FileCache
from cachecontrol.heuristics import ExpiresAfter


class Server:
    enabled = True
    id = None
    lang = 'en'
    locale = 'enUS'
    session = None
    settings = None
    dirty = False

    def __init__(self, session, settings):
        self.settings = settings
        self.session = session
        self.session.headers = self.get_header()

    def get_base_url(self):
        raise NotImplementedError

    def get_header(self):

        return {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "Accept-Language": "en,en-US;q=0.9",
            "Connection": "keep-alive",
            "Origin": self.get_base_url(),
            "Referer": self.get_base_url(),
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/11.0"
        }

    def has_login(self): return False
    def has_free_chapters(self): return True

    def is_session_dirty(self):
        return self.dirty

    def set_session_dirty(self, value=True):
        self.dirty = value

    def login(self, username, password):
        return False

    def relogin(self):
        self.session.cookies.clear()

        credential = self.settings.get_credentials(self.id)
        if credential:
            return self.login(credential[0], credential[1])
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

    def download_cover(self, manga_data):
        r = self.session.get(manga_data["cover"])
        with open(self.settings.get_cover_path(manga_data), 'wb') as fp:
            fp.write(r.content)

    def download_chapter(self, manga_data, chapter_data):
        with requests_cache.disabled():
            list_of_pages = self.get_manga_chapter_data(manga_data, chapter_data)
            dir_path = self.settings.get_chapter_dir(manga_data, chapter_data)
            for index, page_data in enumerate(list_of_pages):
                full_path = os.path.join(dir_path, Server.get_page_name_from_index(index) + ".png")
                self.save_chapter_page(page_data, full_path)

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
        return dict(server_id=self.id, id=id, name=name, cover=None, chapters={})

    def update_chapter_data(self, manga_data, id, title, number, premium=False, read=False, incomplete=False, date=None):
        id = str(id)
        assert isinstance(number, int)
        new_values = dict(id=id, title=title, number=number, premium=premium, read=read, incomplete=False, data=date)
        if id in manga_data["chapters"]:
            manga_data["chapters"][id].update(new_values)
        else:
            manga_data["chapters"][id] = new_values

    def create_page_data(self, url, id=None, encryption_key=None):
        return dict(url=url, id=id, encryption_key=encryption_key)
