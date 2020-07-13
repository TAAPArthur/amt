import requests
import os
import pickle
from manga_reader.password_manager import PasswordManager
from cachecontrol import CacheControl
from cachecontrol.caches.file_cache import FileCache
from cachecontrol.heuristics import ExpiresAfter


USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; WOW64) Gecko/20100101 Firefox/60'


class Server:
    enabled = True
    has_login = False
    headers = {
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Encoding': 'gzip, deflate, br',
        'Accept-Language': 'en,en-US;q=0.9',
        'Connection': 'keep-alive',
        'DNT': '1',
        'Origin': 'https://www.crunchyroll.com',
        'User-Agent': USER_AGENT,
    }
    id = None
    lang = 'en'
    locale = 'enUS'
    session = None
    settings = None

    def __init__(self, settings):
        self.settings = settings
        if not self.load_session():
            if settings.cache:
                self.session = CacheControl(requests.Session(), heuristic=ExpiresAfter(days=1), cache=FileCache('.web_cache', forever=True))
            else:
                self.session = requests.Session()

        self.session.headers = self.headers

    def login(self, username, password):
        return False

    def relogin(self):
        self.session.cookies.clear()

        credential = PasswordManager.get(self.id)
        if credential:
            self.logged_in = self.login(credential[0], credential[1])

    def load_session(self):
        """ Load session from disk """

        file_path = os.path.join(self.settings.cache_dir, '{0}.pickle'.format(self.id))
        try:
            with open(file_path, 'rb') as f:
                self.session = pickle.load(f)
                return True
        except FileNotFoundError:
            pass
        return False

    def save_session(self):
        """ Save session to disk """

        file_path = os.path.join(self.settings.cache_dir, '{0}.pickle'.format(self.id))
        with open(file_path, 'wb') as f:
            pickle.dump(self.session, f)

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
        list_of_pages = self.get_manga_chapter_data(manga_data, chapter_data)
        dir_path = self.settings.get_chapter_dir(manga_data, chapter_data)
        for index, page_data in enumerate(list_of_pages):
            full_path = os.path.join(dir_path, Server.get_page_name_from_index(index))
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
        return dict(server_id=self.id, id=id, name=name, chapters={})

    def update_chapter_data(self, manga_data, id, title, number, read=False, date=None):

        new_values = dict(id=id, title=title, number=number, read=read, data=date)
        if id in manga_data["chapters"]:
            manga_data["chapters"][id].update(new_values)
        else:
            manga_data["chapters"][id] = new_values

    def create_page_data(self, url, id=None, encryption_key=None):
        return dict(url=url, id=id, encryption_key=encryption_key)
