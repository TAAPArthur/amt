import json
import logging
import os
import re

from bs4 import BeautifulSoup

from ..server import ANIME, Server


class Animelab(Server):
    #id = 'animelab'
    has_login = True
    domain = "animelab.com"
    media_type = ANIME
    extension = "mp4"

    base_url = "https://www.animelab.com"
    search_url = base_url + "/shows/autocomplete?searchTerms={}"
    search_info_url = base_url + "/shows/search?searchTerms={}"
    series_url = base_url + "/shows/{}"
    populars_url = base_url + "/api/shows/popular?limit=5&page=1"
    episode_url = base_url + "/api/videoentries/show/{}?limit=99"
    video_url = base_url + "/api/videos/show/{}/subtitles?videoId={}&position=2&forward=true"
    login_url = base_url + "/login"

    stream_url_regex = re.compile(r"https://www.animelab.com/player/(\w*)")
    series_info_url_regex = re.compile(r"var seasonShelf\s*=\s*(.*);")
    series_info_from_player_regex = re.compile(r"var videos = new AnimeLabApp.VideoCollection\((.*)\);\s*$")

    def needs_authentication(self):
        return not self.session.cookies.get("rememberme", domain=self.domain)

    def login(self, username, password):
        r = self.session_post(self.login_url,
                              data={'email': username, 'password': password, "rememberMe": "true"},
                              )

        data = r.json()
        # No premium support yet
        self.is_premium = False
        return True

    def get_media_list(self):
        r = self.session_get_cache(self.populars_url)
        media_data = []
        for series in r.json()["list"]:
            for season in series["seasons"]:
                media_data.append(self.create_media_data(id=series["id"], name=series["name"], season_id=season["id"], season_title=season["name"]))
        return media_data

    def search(self, term):
        r = self.session_get_cache(self.search_url.format(term))
        data = r.json()["data"]
        media_data = []
        for name in data[:5]:
            r = self.session_get_cache(self.search_info_url.format(name))
            match = self.series_info_url_regex.search(r.text)
            url = self.base_url + json.loads(match.group(1))["collection"]["url"]
            data = self.session_get_cache(url).json()["list"]
            seasons = {episode["season"]["id"]: episode["season"]for episode in data}
            for season in seasons.values():
                media_data.append(self.create_media_data(id=season["showId"], name=season["showTitle"], season_id=season["id"], season_title=season["name"]))
        return media_data

    def update_media_data(self, media_data):
        r = self.session_get_cache(self.episode_url.format(media_data["id"]))
        for episode in r.json()["list"]:
            if episode["season"]["id"] == media_data["season_id"]:
                self.update_chapter_data(media_data, id=episode["videoList"][0]["id"], number=episode['episodeNumber'], title=episode['name'])

    def get_media_data_from_url(self, url):
        chapter_slug = self.stream_url_regex.match(url).group(1)
        r = self.session_get_cache(url)
        match = self.series_info_from_player_regex.search(r.text)
        data = json.loads(match.group(1))
        for episode in data:
            if episode["videoEntry"] == chapter_slug:
                season = episode["season"]
                media_data = self.create_media_data(id=season["showId"], name=season["showTitle"], season_id=season["id"], season_title=season["name"])
                self.update_media_data(media_data)
                return media_data

    def get_stream_urls(self, media_data=None, chapter_data=None, url=None):
        r = self.session_get(self.video_url.format(media_data["id"], chapter_data["id"]))
        data = r.json()
        videos = []
        for data in r.json():
            if int(data["id"]) == int(chapter_data["id"]):
                for video in data["videoInstances"]:
                    if video["httpUrl"] and video["videoQuality"]["videoFormat"]["name"] == "MP4":
                        videos.append((video["bitrate"], video["httpUrl"]))
        videos.sort(reverse=True)
        return [x[1] for x in videos]

    def _get_page_path(self, media_data, chapter_data, dir_path, index, page_data):
        return os.path.join(dir_path, "{}.{}".format(chapter_data["id"], page_data["ext"]))
