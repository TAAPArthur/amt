import re

from bs4 import BeautifulSoup
from requests.exceptions import JSONDecodeError

from ..server import Server
from ..util.media_type import MediaType


class GenericFunimation(Server):
    alias = "funimation"

    CSRF_NAME = "csrfmiddlewaretoken"
    domain = "funimation.com"
    base_url = f"https://{domain}"
    login_url = "https://www.funimation.com/log-in/"
    prod_api_base = "https://prod-api-funimationnow.dadcdigital.com"
    login_api_url = prod_api_base + "/api/auth/login/"
    episode_url = prod_api_base + "/api/funimation/episodes/?limit=30&title_id={}"

    api_base = "https://www.funimation.com/api"
    show_api_url = api_base + "/experience/{}/"
    sources_api_url = api_base + "/showexperience/{}/?pinst_id=23571113"

    media_type = MediaType.ANIME
    slow_download = True

    fuzzy_search = True

    def _get_csrf(self):
        r = self.session_get(self.login_url)
        soup = self.soupify(BeautifulSoup, r)
        return soup.find("input", {"name": self.CSRF_NAME})["value"]

    def needs_authentication(self):
        return not self.session.cookies.get("src_user_id", domain=self.domain)

    @property
    def is_premium(self):
        state = self.session.cookies.get("rlildup", domain=self.domain)
        return "premium" in state.lower() if state else False

    def login(self, username, password):

        r = self.session_post(self.login_api_url,
                              data={"username": username, "password": password, self.CSRF_NAME: self._get_csrf()},
                              headers={"Referer": "https://www.funimation.com/log-in/"})

        data = r.json()
        try:
            self.session_set_cookie("src_token", data["token"])
            self.session_set_cookie("src_user_id", str(data["user"]["id"]))
            self.session_set_cookie("rlildup", data["rlildup_cookie"])
            return True
        except KeyError:
            self.logger.info(data["error"])
            return False

    def get_subtitle_info(self, media_data, chapter_data):
        r = self.session_get(self.show_api_url.format(chapter_data["alt_id"]))

        for season in r.json()["seasons"]:
            for chapter in season["episodes"]:
                if media_data["lang"].lower() in chapter["languages"]:
                    video = chapter["languages"][media_data["lang"].lower()]["alpha"]
                    exp = video["simulcast"] if "simulcast" in video else video["uncut"]
                    if exp["experienceId"] == int(chapter_data["alt_id"]) and "textTracks" in exp["sources"][0]:
                        for track in exp["sources"][0]["textTracks"]:
                            yield track["language"], track["src"], None, False
                        break

    def get_stream_urls(self, media_data=None, chapter_data=None):
        chapter_id = chapter_data["alt_id"]
        r = self.session_get(self.sources_api_url.format(chapter_id))
        urls = [(item["videoType"] != "m3u8", [item["src"]]) for item in r.json()["items"]]
        urls = list(map(lambda x: x[1], sorted(urls)))
        return urls

    def backoff(self, c, r):
        try:
            data = r.json()
            if r.json()["status_code"] == "1-02-00-403":
                self.logger.debug(data)
                r.raise_for_status()
        except JSONDecodeError:
            pass
        super().backoff(c, r)


class Funimation(GenericFunimation):
    id = "funimation"

    search_url = "https://www.funimation.com/search/videos/{}/?q={}&cat=shows"
    list_url = "https://funimation.com"
    new_api_episode_url = "https://title-api.prd.funimationsvc.com/v1/shows/{}/episodes/{}/?region=US&deviceType=web&locale=en"
    stream_url_regex = re.compile("funimation.com/(?:v|en/shows)/([^/]*)/([^/]*)")
    watch_next_url = "https://www.funimation.com/api/episodes/watchnext/?title_id={}&sort=order&sort_direction=ASC"

    def _get_media_list(self, ids, limit=None):
        media_data = []
        for id in ids[:limit]:
            data = self.session_get_cache_json(self.episode_url.format(id))
            if not data["count"]:
                continue
            season_data = {(item["item"]["titleId"], item["item"]["titleName"], item["item"]["seasonId"], item["item"]["seasonTitle"], audio) for item in data["items"] for audio in item["audio"]}
            experiences = {item["item"]["seasonId"]: item["mostRecentSvod"]["experience"] for item in data["items"]}

            for media_id, media_title, seasonId, seasonTitle, lang in season_data:
                experience = experiences[seasonId]
                media_data.append(self.create_media_data(id=media_id, name=media_title, season_id=seasonId, season_title=seasonTitle, alt_id=experience, lang=lang.lower()))

        return media_data

    def get_media_list(self, limit=2, **kwargs):
        soup = self.soupify(BeautifulSoup, self.session_get(self.list_url))
        ids = []
        for item in soup.findAll("div", {"class": "slide"})[:limit]:
            ids.append(item["data-id"])
        return self._get_media_list(ids, limit=limit)

    def search_for_media(self, term, alt_id=None, limit=2, **kwargs):
        soup = self.soupify(BeautifulSoup, self.session_get(self.search_url.format(str(1), term)))
        show_url_regex = re.compile("/shows/([^/]*)/")

        chapter_ids = []
        for i in range(1, 10):
            starting_len = len(chapter_ids)
            soup = self.soupify(BeautifulSoup, self.session_get(self.search_url.format(str(i), term)))
            for div in soup.findAll("div", {"class": "product-results"}):
                title_id = div["data-id"]
                item = div.find("a", {"class": "show-title"})
                url = item["href"]
                match = show_url_regex.search(url)
                slug = match.group(1) if match else None
                if not slug or term.lower() not in slug.lower():
                    continue
                chapter_ids.append(title_id)
                continue

            if starting_len == len(chapter_ids) or (limit and len(chapter_ids) >= limit):
                break

        return self._get_media_list(chapter_ids)

    def _get_episode_id(self, url):
        match = self.stream_url_regex.search(url)
        r = self.session_get(self.new_api_episode_url.format(match.group(1), match.group(2)))
        video_info = []
        for video in r.json()["videoList"]:
            lang_code_score = [self.settings.get_prefered_lang_key(self, lang=lang["languageCode"]) for lang in video["spokenLanguages"]]
            lang_name_score = [self.settings.get_prefered_lang_key(self, lang=lang["name"]) for lang in video["spokenLanguages"]]
            video_info.append((min(lang_code_score + lang_name_score), video["id"]))
        return str(min(sorted(video_info))[1])

    def update_media_data(self, media_data: dict, r=None):
        if not r:
            r = self.session_get(self.show_api_url.format(media_data["alt_id"]))

        for season in r.json()["seasons"]:
            if season["seasonPk"] == media_data["season_id"]:
                for chapter in season["episodes"]:
                    if chapter["languages"] and media_data["lang"] in chapter["languages"]:
                        video = chapter["languages"][media_data["lang"]]["alpha"]
                        exp = video["simulcast"] if "simulcast" in video else video["uncut"]
                        alt_exp = video["uncut"] if "uncut" in video else video["simulcast"]
                        premium = exp["svodOnly"]
                        special = chapter["mediaCategory"] != "episode"
                        self.update_chapter_data(media_data, id=alt_exp["experienceId"], number=chapter["episodeId"], title=chapter["episodeTitle"], premium=premium, special=special, alt_id=exp["experienceId"])

    def get_all_media_data_from_url(self, url):
        chapter_id = self._get_episode_id(url)
        r = self.session_get(self.show_api_url.format(chapter_id))
        data = r.json()
        media_list = []
        for season in data["seasons"]:
            for episode in season["episodes"]:
                for lang, videos in episode["languages"].items():
                    video = videos["alpha"]
                    for typeKey in ("simulcast", "uncut"):
                        if typeKey not in video:
                            continue
                        exp = video[typeKey]
                        media_data = self.create_media_data(id=data["showId"], name=data["showTitle"], season_id=season["seasonPk"], season_title=season["seasonTitle"], alt_id=chapter_id, lang=lang.lower())
                        if int(exp["experienceId"]) == int(chapter_id):
                            self.update_media_data(media_data, r=r)
                            media_list.insert(0, media_data)
                        else:
                            media_list.append(media_data)
        return media_list

    def get_chapter_id_for_url(self, url):
        chapter_id = self._get_episode_id(url)
        return chapter_id


class FunimationLibrary(GenericFunimation):
    id = "funimationlib"
    has_free_chapters = False
    need_to_login_to_list = True

    list_url = GenericFunimation.prod_api_base + "/api/funimation/library/"
    search_url = GenericFunimation.prod_api_base + "/api/funimation/library/?search={}"
    episode_url = GenericFunimation.prod_api_base + "/api/funimation/library/?show={}&season={}"
    languages = ["Japanese", "English"]

    def _get_media_list_helper(self, data):
        for media_info in data["items"]:
            for season in media_info["seasons"]:
                for lang in self.languages:
                    yield self.create_media_data(id=media_info["slug"], name=media_info["title"], season_id=season["id"], season_title=season["title"], alt_id=media_info["id"], lang=lang, season_number=season["number"])

    def get_auth_header(self):
        t = self.session.cookies.get("src_token", domain=self.domain)
        return {"Authorization": "Token " + t}

    def get_media_list(self, limit=None, **kwargs):
        data = self.session.get(self.list_url, headers=self.get_auth_header()).json()
        yield from self._get_media_list_helper(data)

    def search_for_media(self, term, limit=None, **kwargs):
        data = self.session.get(self.search_url.format(term), headers=self.get_auth_header()).json()
        yield from self._get_media_list_helper(data)

    def update_media_data(self, media_data):
        data = self.session.get(self.episode_url.format(media_data["alt_id"], media_data["season_number"]), headers=self.get_auth_header()).json()
        for media_info in data["items"]:
            for season in media_info["seasons"]:
                if season["id"] == media_data["season_id"]:
                    for chapter in season["episodes"]:
                        exp = list(filter(lambda x: x["language"] == media_data["lang"], chapter["experiences"]))
                        if exp:
                            self.update_chapter_data(media_data, id=chapter["id"], number=chapter["number"] or 1, title=chapter["title"], premium=True, alt_id=exp[-1]["id"])
