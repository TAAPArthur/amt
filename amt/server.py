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

    static_pages = False
    has_anime = False
    has_media = True
    has_login = False
    has_free_chapters = True
    has_gaps = False
    auto_select = False
    is_non_premium_account = False

    def __init__(self, session, settings=None):
        self.settings = settings
        self.session = session

    def _request(self, get, url, **kwargs):
        logging.info(url)
        r = self.session.get(url, **kwargs) if get else self.session.post(url, **kwargs)
        if r.status_code != 200:
            logging.warning(r)
        return r

    def session_get(self, url, **kwargs):
        return self._request(True, url, **kwargs)

    def session_post(self, url, **kwargs):
        return self._request(False, url, **kwargs)

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
        return '%03d' % page_index

    def needs_authentication(self):
        return self.has_login

    def download_chapter(self, media_data, chapter_data, page_limit=None):
        logging.info("Starting download of %s %s", media_data["name"], chapter_data["title"])
        if chapter_data["premium"]:
            if self.needs_authentication():
                logging.debug("Server is not authenticated; relogging in")
                if not self.relogin():
                    logging.info("Cannot access chapter %s #%s %s because credentials are invalid", media_data["name"], str(chapter_data["number"]), chapter_data["title"])
                    return False
            if self.is_non_premium_account:
                logging.info("Cannot access chapter %s #%s %s because account is not premium", media_data["name"], str(chapter_data["number"]), chapter_data["title"])
                return False

        list_of_pages = self.get_media_chapter_data(media_data, chapter_data)
        dir_path = self.settings.get_chapter_dir(media_data, chapter_data)
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
        logging.info("%s %d %s is downloaded", media_data["name"], chapter_data["number"], chapter_data["title"])
        return downloaded_page

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

    def create_media_data(self, id, name, cover=None):
        return dict(server_id=self.id, id=id, name=name, cover=None, progress=0, chapters={})

    def update_chapter_data(self, media_data, id, title, number, premium=False, date=None):
        id = str(id)
        special = False
        try:
            number = float(number)
        except ValueError:
            special = True
            number = float(number.replace("-", "."))

        new_values = dict(id=id, title=title, number=number, premium=premium, special=special, data=date)
        if id in media_data["chapters"]:
            media_data["chapters"][id].update(new_values)
        else:
            media_data["chapters"][id] = new_values
            media_data["chapters"][id]["read"] = False

    def create_page_data(self, url, id=None, encryption_key=None):
        return dict(url=url, id=id, encryption_key=encryption_key)
