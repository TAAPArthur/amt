import logging
import os
import re
from shlex import quote

from ..server import Server
from ..util.media_type import MediaType


class GenericCrunchyrollServer(Server):
    alias = "crunchyroll"

    api_auth_url = "https://api-manga.crunchyroll.com/cr_authenticate?session_id={}&version=0&format=json"
    start_session_url = "https://api.crunchyroll.com/start_session.0.json"
    login_url = "https://api.crunchyroll.com/login.0.json"

    _access_token = "WveH9VkPLrXvuNm"
    _access_type = "com.crunchyroll.crunchyroid"

    def get_session_id(self):
        if Crunchyroll._api_session_id:
            return Crunchyroll._api_session_id
        data = self.session_post(
            self.start_session_url,
            data={
                "device_id": "1234567",
                "device_type": self._access_type,
                "access_token": self._access_token,
            }
        ).json()["data"]
        Crunchyroll._api_session_id = data["session_id"]
        return Crunchyroll._api_session_id

    def _store_login_data(self, data):
        Crunchyroll._api_auth_token = data["data"]["auth"]
        self.is_premium = data["data"]["user"]["premium"]

    def needs_authentication(self):
        if Crunchyroll._api_auth_token:
            return False
        r = self.session_get(self.api_auth_url.format(self.get_session_id()))
        data = r.json()
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


"""
Crunchyroll Manga's api doesn't seem to allow getting a list of series nor searching through them
There aren't that many manga, so here is a hard coded list
"""
SERIES_DATA = {
    179: "Attack on Titan",
    181: "Space Brothers",
    205: "UQ HOLDER!",
    237: "Sun-Ken Rock",
    245: "Silver Nina",
    247: "Inside Mari",
    249: "Love Theory",
    261: "Orange",
    263: "Star Light Woman",
    265: "Is this Girl for Real!?",
    267: "Okitenemuru",
    271: "King's Game: Origin",
    273: "ReCollection",
    275: "Action Mask",
    277: "Arpeggio of Blue Steel",
    279: "Spirit Circle",
    281: "Shindo",
    283: "Buffalo 5 Girls",
    287: "Investor Z",
    291: "Memoirs of Amorous Gentlemen",
    293: "The Diary of Ochibi",
    301: "The Heroic Legend of Arslan",
    305: "Ajin : Demi-Human",
    313: "Insufficient Direction",
    317: "The Tenth Prism",
    335: "Joshi Kausei",
    337: "Girl May Kill",
    341: "Cronos Haze",
    345: "Murder Incarnation",
    351: "The Legend of Onikirimaru",
    353: "Bokura wa Minna Kawaisou",
    385: "HYPERSONIC music club",
    389: "Donyatsu",
    397: "Tales of Wedding Rings",
    409: "Aizawa-san Multiplies",
    411: "Father and Son",
    413: "Scum's wish",
    423: "The Morose Mononokean",
    433: "Arakawa Under the Bridge",
    463: "The Daily Life of Crunchyroll-Hime",
    469: "The Grim Reaper and an Argent Cavalier",
    477: "Restaurant to Another World",
    479: "Knight's & Magic",
    481: "Final Fantasy Lost Stranger",
    487: "APOSIMZ",
    491: "Drifting Dragons",
    493: "Farewell, My Dear Cramer",
    495: "Grand Blue Dreaming",
    499: "To Your Eternity",
    507: "EDENS ZERO",
    511: "Holmes of Kyoto",
    513: "Crossing Time",
    515: "Honkai Impact 3rd",
    517: "YanOta: The Delinquent and the Otaku",
    519: "Talentless Nana",
    521: "Lofty Flower, fall for me!!",
    523: "One Room of Happiness",
    527: "Genshin Impact",
    528: "Kiana Plays Honkai",
    529: "Elan Palatinus",
    530: "London Holiday",
    531: "Springfest",
    532: "Moon Shadow",
    533: "Second Key",
    534: "ASHIDAKA - The Iron Hero",
    535: "Cardcaptor Sakura: Clear Card",
    536: "The Ghost in the Shell: The Human Algorithm",
    537: "A Sign of Affection",
    539: "Alien Space",
    540: "Shangri-La Frontier",
    541: "Muv-Luv Alternative",
    542: "Four Knights of the Apocalypse",
}


class Crunchyroll(GenericCrunchyrollServer):
    id = "crunchyroll"

    base_url = "https://www.crunchyroll.com"
    manga_url = base_url + "/comics/manga/{0}/volumes"

    api_base_url = "https://api-manga.crunchyroll.com"
    api_series_url = api_base_url + "/series?sort=popular"
    api_chapter_url = api_base_url + "/list_chapter?session_id={}&chapter_id={}&auth={}"
    api_chapters_url = api_base_url + "/chapters?series_id={}"

    _api_auth_token = None
    _api_session_id = None
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
        return [self.create_media_data(id=id, name=name, locale="enUS") for id, name in SERIES_DATA.items()][:limit]

    def search(self, term, limit=None):
        regex = re.compile(r"[^\w\d]")
        term = regex.sub("", term.lower())
        return list(filter(lambda x: term in regex.sub("", x["name"].lower()), self.get_media_list()))[:limit]

    def update_media_data(self, media_data: dict):
        r = self.session_get(self.api_chapters_url.format(media_data["id"]))

        json_data = r.json()
        # resp_data = json_data["series"]
        chapters = json_data["chapters"]

        # Chapters
        for chapter in chapters:
            date = None
            raw_date_str = chapter.get("availability_start", chapter.get("updated"))
            if raw_date_str:
                date = raw_date_str.split(" ")[0]

            self.update_chapter_data(media_data, id=chapter["chapter_id"], number=chapter["number"], title=chapter["locale"][media_data["locale"]]["name"], premium=not chapter["viewable"], date=date)

    def get_media_chapter_data(self, media_data, chapter_data):
        r = self.session_get(self.api_chapter_url.format(self.get_session_id(), chapter_data["id"], Crunchyroll._api_auth_token))
        raw_pages = r.json()["pages"]
        raw_pages.sort(key=lambda x: int(x["number"]))
        pages = [self.create_page_data(url=page["locale"][media_data["locale"]][self.page_url_key]) for page in raw_pages if page["locale"]]

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
    bandwidth_regex = re.compile(r"BANDWIDTH=([0-9]*),")
    series_url = api_base_url + "/list_collections.0.json?media_type=anime&session_id={}&series_id={}"
    media_type = MediaType.ANIME

    stream_url_regex = re.compile(r"crunchyroll.com/([^/]*)/.*-(\d+)$")

    extension = "ts"

    def _create_media_data(self, series_id, item_alt_id, season_id=None):
        r = self.session_get(self.series_url.format(self.get_session_id(), series_id))
        season_data = r.json()["data"]
        unique_seasons = len(set(map(lambda x: x["season"], season_data))) == len(season_data)
        for season in season_data:
            if not season_id or season["collection_id"] == season_id:
                yield self.create_media_data(id=series_id, name=season["name"], season_id=season["collection_id"], season_title=season["season"] if unique_seasons else season["collection_id"], dir_name=item_alt_id)

    def get_media_list(self, limit=None):
        return self.search("", limit=limit)

    def search(self, term, limit=None):
        r = self.session_get(self.search_series.format(self.get_session_id(), term.replace(" ", "%20"), limit if limit else 0) if term else self.list_all_series.format(self.get_session_id()))
        data = r.json()["data"]
        media_data = []
        for item in data:
            item_alt_id = item["url"].split("/")[-1]
            media_data += list([media for media in self._create_media_data(item["series_id"], item_alt_id)])

        return media_data

    def update_media_data(self, media_data: dict):
        r = self.session_get(self.list_media.format(self.get_session_id(), media_data["id"]))
        data = r.json()["data"]
        for chapter in data:
            if chapter["collection_id"] == media_data["season_id"] and not chapter["clip"]:
                special = False
                if chapter["episode_number"] and chapter["episode_number"][-1].isalpha():
                    special = True
                    chapter["episode_number"] = chapter["episode_number"][:-1]

                self.update_chapter_data(media_data, id=chapter["media_id"], number=chapter["episode_number"], title=chapter["name"], premium=not chapter["free_available"], special=special)

    def get_media_data_from_url(self, url):

        match = self.stream_url_regex.search(url)
        media_name_hint = match.group(1)
        # media_name_prefix_hint = media_name_hint.split("-")[0]
        chapter_id = match.group(2)
        r = self.session_get(self.episode_url.format(self.get_session_id(), chapter_id))
        data = r.json()["data"]
        media_data = next(self._create_media_data(data["series_id"], media_name_hint, season_id=data["collection_id"]))
        self.update_media_data(media_data)
        assert chapter_id in media_data["chapters"]
        return media_data

    def get_chapter_id_for_url(self, url):
        chapter_id = url.split("-")[-1]
        return chapter_id

    def get_stream_urls(self, media_data=None, chapter_data=None):
        chapter_id = chapter_data["id"]

        r = self.session_get(self.stream_url.format(self.get_session_id(), chapter_id))
        stream = r.json()["data"]["stream_data"]["streams"][0]

        r = self.session_get(stream["url"])
        bandwidth = None
        url_bandwidth_tuples = []
        for line in r.text.splitlines():
            if line.startswith("#"):
                match = self.bandwidth_regex.search(line)
                if match:
                    bandwidth = int(match.group(1))
            elif line:
                url_bandwidth_tuples.append((bandwidth, line))
        url_bandwidth_tuples.sort(reverse=True)
        url_bandwidth_tuples.append((0, stream["url"]))

        return map(lambda x: x[1], url_bandwidth_tuples)

    def post_download(self, media_data, chapter_data, dir_path):
        pathWithoutExt = os.path.join(dir_path, chapter_data["id"])
        self.settings.convert(self.extension, f"{quote(dir_path)}/*.{self.extension}", pathWithoutExt)

    def get_stream_data(self, media_data, chapter_data):
        import m3u8
        m3u8_url = self.get_stream_url(media_data=media_data, chapter_data=chapter_data)
        return [self.create_page_data(url=segment.uri, encryption_key=segment.key) for segment in m3u8.load(m3u8_url).segments]

    def get_media_chapter_data(self, media_data, chapter_data):
        return self.get_stream_data(media_data, chapter_data)
