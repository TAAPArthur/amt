import logging
import os
import re

from bs4 import BeautifulSoup

from ..server import ANIME, Server


class Funimation(Server):
    id = "funimation"

    CSRF_NAME = "csrfmiddlewaretoken"
    domain = "funimation.com"
    login_url = "https://www.funimation.com/log-in/"
    api_base = "https://www.funimation.com/api"
    login_api_url = "https://prod-api-funimationnow.dadcdigital.com/api/auth/login/"
    show_api_url = api_base + "/experience/{}/"
    sources_api_url = api_base + "/showexperience/{}/?pinst_id=23571113"
    episode_url = "https://prod-api-funimationnow.dadcdigital.com/api/funimation/episodes/?limit=99999&title_id={}"

    season_regex = re.compile(r"var titleData\s*=\s*(.*)")
    player_regex = re.compile(r"/player/(\d*)")

    search_url = "https://api-funimation.dadcdigital.com/xml/longlist/content/page/?id=search&q={}"
    list_url = "https://api-funimation.dadcdigital.com/xml/longlist/content/page/?id=shows&limit=5"
    # list_url = "https://prod-api-funimationnow.dadcdigital.com/api/funimation/shows/"

    media_type = ANIME
    stream_url_regex = re.compile(r"funimation(.com|now.uk)")
    showID_regex = re.compile(r"KANE_customdimensions.showID = '(\d*)'")
    extension = "mp4"

    def _get_csrf(self):
        r = self.session_get(self.login_url)
        soup = self.soupify(BeautifulSoup, r)
        return soup.find("input", {"name": self.CSRF_NAME})["value"]

    def needs_authentication(self):
        if self.session.cookies.get("src_user_id", domain=self.domain):
            return False
        return True

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
            self.session.cookies.set("src_token", data["token"], domain=self.domain)
            self.session.cookies.set("src_user_id", str(data["user"]["id"]), domain=self.domain)
            self.session.cookies.set("rlildup", data["rlildup_cookie"], domain=self.domain)
            return True
        except KeyError:
            logging.info(data["error"])
            return False

    def _get_media_list(self, url, limit=-1):
        r = self.session_get(url)
        soup = self.soupify(BeautifulSoup, r)
        media_data = []
        for item in soup.findAll("item")[:limit]:
            title = item.find("title").text
            id = item.find("id").text
            r = self.session_get(self.episode_url.format(id))
            data = r.json()
            season_data = {(item["item"]["seasonId"], item["item"]["seasonTitle"], audio) for item in data["items"] for audio in item["audio"]}
            experiences = {item["item"]["seasonId"]: item["mostRecentSvod"]["experience"] for item in data["items"]}

            for seasonId, seasonTitle, lang in season_data:
                experience = experiences[seasonId]
                media_data.append(self.create_media_data(id=id, name=title, season_id=seasonId, season_title=seasonTitle, alt_id=experience, lang=lang.lower()))

        return media_data

    def get_media_list(self):
        return self._get_media_list(self.list_url)

    def search(self, term, alt_id=None):
        return self._get_media_list(self.search_url.format(term.replace(" ", "%20")), limit=2)

    def _get_episode_id(self, url):
        r = self.session_get(url)

        match = self.showID_regex.search(r.text)
        showID = match.group(1)

        soup = self.soupify(BeautifulSoup, r)
        src = soup.find("iframe", {"name": "player"})["src"]
        match = self.player_regex.search(src)
        return int(match.group(1)), showID

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
                        self.update_chapter_data(media_data, id=exp["experienceId"], number=chapter["episodeId"], title=chapter["episodeTitle"], premium=premium, special=special, alt_id=alt_exp["experienceId"])

    def get_media_data_from_url(self, url):
        chapter_id, _ = self._get_episode_id(url)
        r = self.session_get(self.show_api_url.format(chapter_id))
        data = r.json()
        for season in data["seasons"]:
            for episode in season["episodes"]:
                for lang, videos in episode["languages"].items():
                    video = videos["alpha"]
                    for typeKey in ("simulcast", "uncut"):
                        if typeKey not in video:
                            continue
                        exp = video[typeKey]
                        if int(exp["experienceId"]) == int(chapter_id):
                            media_data = self.create_media_data(id=data["showId"], name=data["showTitle"], season_id=season["seasonPk"], season_title=season["seasonTitle"], alt_id=chapter_id, lang=lang.lower())
                            self.update_media_data(media_data, r=r)
                            return media_data

    def get_chapter_id_for_url(self, url):
        chapter_id, media_id = self._get_episode_id(url)
        return chapter_id

    def get_stream_urls(self, media_data=None, chapter_data=None, url=None):
        if url:
            chapter_id, _ = self._get_episode_id(url)
        else:
            chapter_id = chapter_data["id"]

        r = self.session_get(self.sources_api_url.format(chapter_id))

        # r.json()["items"] returns a list of mp4 and m38 streams
        logging.info("Sources: %s", [item["src"] for item in r.json()["items"]])
        return [item["src"] for item in r.json()["items"]]

    def download_subtitles(self, media_data, chapter_data, dir_path):
        r = self.session_get(self.show_api_url.format(chapter_data["id"]))

        for season in r.json()["seasons"]:
            for chapter in season["episodes"]:
                try:
                    video = chapter["languages"][media_data["lang"]]["alpha"]
                    exp = video["simulcast"] if "simulcast" in video else video["uncut"]
                    if exp["experienceId"] == int(chapter_data["id"]):
                        for track in exp["sources"][0]["textTracks"]:
                            if self.settings.is_allowed_text_lang(track["language"], media_data):
                                subtitle_src = track["src"]
                                _, ext = os.path.splitext(subtitle_src)
                                path = os.path.join(dir_path, str(chapter_data["id"]) + ext)
                                if not os.path.exists(path):
                                    r = self.session_get(subtitle_src)
                                    with open(path, "wb") as fp:
                                        fp.write(r.content)
                        break
                except:
                    pass

    def _get_page_path(self, media_data, chapter_data, dir_path, index, page_data):
        return os.path.join(dir_path, "{}.{}".format(chapter_data["id"], page_data["ext"]))
