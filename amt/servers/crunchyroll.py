import json
import logging
import re

from ..job import Job
from ..server import Server, RequestServer
from ..util.media_type import MediaType


class GenericCrunchyrollServer(Server):
    alias = "crunchyroll"

    api_auth_url = "https://api-manga.crunchyroll.com/cr_authenticate?session_id={}&version=0&format=json"
    base_url = "https://api.crunchyroll.com"
    start_session_url = base_url + "/start_session.0.json"
    login_url = base_url + "/login.0.json"

    _access_token = "WveH9VkPLrXvuNm"
    _access_type = "com.crunchyroll.crunchyroid"

    def get_session_id(self, force=False):
        session_id = self.session_get_cookie("session_id", domain=self.base_url)
        if not force and session_id:
            return session_id
        with self._lock:
            if session_id != self.session_get_cookie("session_id", domain=self.base_url):
                return self.session_get_cookie("session_id", domain=self.base_url)
            data = self.session_post(
                self.start_session_url,
                data={
                    "device_id": "1234567",
                    "device_type": self._access_type,
                    "access_token": self._access_token,
                }
            ).json()["data"]

            assert self.session_get_cookie("session_id", domain=self.base_url) == data["session_id"]
            return data["session_id"]

    def session_get_json(self, url):
        data = self.session_get(url).json()
        if data is not None and data.get("error", False) and data["code"] == "bad_session":
            expired_session_id = self.get_session_id()
            new_session_id = self.get_session_id(force=True)
            new_url = url.replace(expired_session_id, new_session_id)
            data = self.session_get(new_url).json()
        return data

    def _store_login_data(self, data):
        Crunchyroll._api_auth_token = data["data"]["auth"]
        self.is_premium = data["data"]["user"]["premium"]

    def needs_authentication(self):
        if Crunchyroll._api_auth_token:
            return False
        data = self.session_get_json(self.api_auth_url.format(self.get_session_id()))
        if data and "data" in data:
            self._store_login_data(data)
            return False
        if not data or data.get("error", False):
            logging.info("Error authenticating %s", data)
        return True

    def login(self, username, password):
        response = self.session_post(self.login_url,
                                     data={
                                         "session_id": self.get_session_id(),
                                         "account": username,
                                         "password": password
                                     }).json()
        if "data" in response:
            self._store_login_data(response)
            return True
        logging.debug("Login failed; response: %s", response)
        return False


class Crunchyroll(GenericCrunchyrollServer):
    id = "crunchyroll"
    need_cloud_scraper = True

    base_url = "https://www.crunchyroll.com"
    manga_url = base_url + "/comics/manga/{0}/volumes"

    alpha_list_url = base_url + "/comics/manga/alpha?group=all"
    popular_list_url = base_url + "/comics/manga"
    popular_media_regex = re.compile(r"#media_group_(\d*).*bubble_data., (.*)\);")

    api_base_url = "https://api-manga.crunchyroll.com"
    api_series_url = api_base_url + "/series?sort=popular"
    api_chapter_url = api_base_url + "/list_chapter?session_id={}&chapter_id={}&auth={}"
    api_chapters_url = api_base_url + "/chapters?series_id={}"

    _api_auth_token = None
    possible_page_url_keys = ["encrypted_mobile_image_url", "encrypted_composed_image_url"]
    page_url_key = possible_page_url_keys[0]

    stream_url_regex = re.compile(r"crunchyroll.com/manga/([\w-]*)/read/(\d*\.?\d*)")

    def get_media_data_from_url(self, url):
        name_slug = self.stream_url_regex.search(url).group(1)
        return self.search(name_slug)[0]

    def get_chapter_id_for_url(self, url):
        number = self.stream_url_regex.search(url).group(2)
        media_data = self.get_media_data_from_url(url)
        self.update_media_data(media_data)
        for chapter_data in media_data["chapters"].values():
            if chapter_data["number"] == float(number):
                return chapter_data["id"]

    @staticmethod
    def decode_image(buffer):
        # Don't know why 66 is special
        return bytes(b ^ 66 for b in buffer)

    def get_media_list(self, limit=None):
        media_name_ids = {}
        if RequestServer.cloudscraper:
            try:
                from bs4 import BeautifulSoup
                soup = self.soupify(BeautifulSoup, self.session_get(self.alpha_list_url))
                for group_item in soup.findAll("li", {"class": "group-item"}):
                    media_name_ids[group_item["group_id"]] = group_item.find("a")["title"]
            except ImportError:
                pass
            r = self.session_get(self.popular_list_url)
            match = self.popular_media_regex.findall(r.text)
            for media_id, data in match:
                media_name_ids[media_id] = json.loads(data)["name"]

        return list(map(lambda media_id: self.create_media_data(id=media_id, name=media_name_ids[media_id], locale="enUS"), media_name_ids))

    def search(self, term, limit=None):
        regex = re.compile(r"[^\w\d]")
        term = regex.sub("", term.lower())
        return list(filter(lambda x: term in regex.sub("", x["name"].lower()), self.get_media_list()))[:limit]

    def update_media_data(self, media_data: dict):
        json_data = self.session_get_json(self.api_chapters_url.format(media_data["id"]))

        # resp_data = json_data["series"]
        chapters = json_data["chapters"]

        # Chapters
        for chapter in chapters:
            date = None
            raw_date_str = chapter.get("availability_start", chapter.get("updated"))
            if raw_date_str:
                date = raw_date_str.split(" ")[0]

            self.update_chapter_data(media_data, id=chapter["chapter_id"], number=chapter["number"], title=chapter["locale"][media_data["locale"]]["name"], premium=not chapter["viewable"], date=date)

    def get_media_chapter_data(self, media_data, chapter_data, stream_index=0):
        data = self.session_get_json(self.api_chapter_url.format(self.get_session_id(), chapter_data["id"], Crunchyroll._api_auth_token))
        raw_pages = data["pages"]
        raw_pages.sort(key=lambda x: int(x["number"]))
        pages = [self.create_page_data(url=page["locale"][media_data["locale"]][self.page_url_key], ext="jpg") for page in raw_pages if page["locale"]]

        return pages

    def save_chapter_page(self, page_data, path):
        r = self.session_get(page_data["url"])
        buffer = self.decode_image(r.content)
        with open(path, "wb") as fp:
            fp.write(buffer)


class CrunchyrollAnime(GenericCrunchyrollServer):
    id = "crunchyroll_anime"

    api_base_url = "http://api.crunchyroll.com"
    list_all_series = api_base_url + "/list_series.0.json?media_type=anime&session_id={}"
    search_series = api_base_url + "/list_series.0.json?media_type=anime&session_id={}&filter=prefix:{}&limit={}"
    list_media = api_base_url + "/list_media.0.json?limit=2000&media_type=anime&session_id={}&series_id={}"
    stream_url = api_base_url + "/info.0.json?fields=media.stream_data&locale=enUS&session_id={}&media_id={}"
    episode_url = api_base_url + "/info.0.json?session_id={}&media_id={}"
    series_url = api_base_url + "/list_collections.0.json?media_type=anime&session_id={}&series_id={}"
    media_type = MediaType.ANIME

    stream_url_regex = re.compile(r"crunchyroll.com/([^/]*)/.*-(\d+)$")

    def _create_media_data(self, series_id, item_alt_id, season_id=None, limit=None):
        season_data = self.session_get_json(self.series_url.format(self.get_session_id(), series_id))["data"]
        for season in season_data[:limit]:
            if not season_id or season["collection_id"] == season_id:
                yield self.create_media_data(id=series_id, name=season["name"], season_id=season["collection_id"], dir_name=item_alt_id, lang=None)

    def get_media_list(self, limit=4):
        return self.search("", limit=limit)

    def search(self, term, limit=None):
        data = self.session_get_json(self.search_series.format(self.get_session_id(), term, limit if limit else 0) if term else self.list_all_series.format(self.get_session_id()))

        def get_all_seasons(item):
            item_alt_id = item["url"].split("/")[-1]
            return [media for media in self._create_media_data(item["series_id"], item_alt_id)]

        job = Job(self.settings.threads, data["data"][:limit], func=get_all_seasons, raiseException=True)
        return job.run()

    def update_media_data(self, media_data: dict):
        data = self.session_get_json(self.list_media.format(self.get_session_id(), media_data["id"]))["data"]
        for chapter in data:
            if chapter["collection_id"] == media_data["season_id"] and not chapter["clip"]:
                special = False
                number = chapter["episode_number"]
                if chapter["episode_number"] and chapter["episode_number"][-1].isalpha():
                    special = True
                    number = chapter["episode_number"][:-1]
                elif not chapter["episode_number"]:
                    number = 1 if len(data) == 1 else 0

                self.update_chapter_data(media_data, id=chapter["media_id"], number=number, title=chapter["name"], premium=not chapter["free_available"], special=special)

    def get_media_data_from_url(self, url):

        match = self.stream_url_regex.search(url)
        media_name_hint = match.group(1)
        # media_name_prefix_hint = media_name_hint.split("-")[0]
        chapter_id = match.group(2)
        data = self.session_get_json(self.episode_url.format(self.get_session_id(), chapter_id))["data"]
        media_data = next(self._create_media_data(data["series_id"], media_name_hint, season_id=data["collection_id"]))
        return media_data

    def get_chapter_id_for_url(self, url):
        chapter_id = url.split("-")[-1]
        return chapter_id

    def get_stream_urls(self, media_data=None, chapter_data=None):
        chapter_id = chapter_data["id"]

        data = self.session_get_json(self.stream_url.format(self.get_session_id(), chapter_id))
        streams = data["data"]["stream_data"]["streams"]
        return [stream["url"] for stream in streams]
