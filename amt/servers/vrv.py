import json
import os
import re
from collections import defaultdict
from datetime import datetime

from requests_oauthlib import OAuth1

from ..server import ANIME, Server


class Vrv(Server):
    id = "vrv"
    home = "https://vrv.co/"
    media_type = ANIME
    extension = "mp4"
    stream_url_regex = re.compile(r"vrv.co/watch/(\w*)/.+")
    is_premium = True

    api_param_regex = re.compile(r"window.__APP_CONFIG__\s*=\s*(.*);")
    api_state_regex = re.compile(r"window.__INITIAL_STATE__\s*=\s*(.*);")

    subtitle_regex = re.compile(r"\w*-\w\d*_[2-9]\d*$")
    domain = "vrv.co"
    api_base = "https://api.vrv.co"
    login_api_url = api_base + "/core/authenticate/by:credentials"
    key_pair_url = api_base + "/core/index"

    _search_api_url = None
    _series_api_url = None
    _season_api_url = None
    _seasons_api_url = None
    _single_episode_api_url = None
    _apiParams = None
    key_pair = None

    def _load_urls(self):
        if not self.key_pair:
            r = self.session_get(self.key_pair_url)
            data = r.json()
            d = defaultdict(dict)
            for item in data["signing_policies"]:
                d[item["path"]][item["name"]] = item["value"]
            self.key_pair = {path.replace("*", ".*"): "&".join([f"{k}={v}" for k, v in d[path].items()]) for path in d}
            url_ptr = data["__links__"]["cms_index.v2"]["href"]
            r = self.session_get_with_key_pair(self.api_base + url_ptr + "?")
            data = r.json()
            links = data["__links__"]
            self._single_episode_api_url = self.api_base + links["episode"]["href"] + "?"
            self._season_api_url = self.api_base + links["episodes"]["href"].replace("{?", "?season_id={")
            self._seasons_api_url = self.api_base + links["seasons"]["href"].replace("{?", "?series_id={")
            self._series_api_url = self.api_base + links["series"]["href"] + "?"
            self._search_api_url = self.api_base + links["search_results"]["href"] + "?q={}&n={}"

    @property
    def series_api_url(self):
        self._load_urls()
        return self._series_api_url

    @property
    def search_api_url(self):
        self._load_urls()
        return self._search_api_url

    @property
    def season_api_url(self):
        self._load_urls()
        return self._season_api_url

    @property
    def seasons_api_url(self):
        self._load_urls()
        return self._seasons_api_url

    @property
    def single_episode_api_url(self):
        self._load_urls()
        return self._single_episode_api_url

    def session_get_with_key_pair(self, url):
        self._load_urls()
        for path in self.key_pair:
            if re.search(path, url):
                url += "&" + self.key_pair[path]
                return self.session_get_mem_cache(url)
                break
        assert False
        return self.session_get_mem_cache(url)

    @property
    def apiParams(self):
        if not self._apiParams:
            r = super().session_get(self.home, auth=False)
            match = self.api_param_regex.search(r.text)
            self._apiParams = json.loads(match.group(1))["cxApiParams"]
        return self._apiParams

    @property
    def oauth_token(self):
        return self.session.cookies.get("oauth_token", domain=self.domain)

    @property
    def oauth_token_secret(self):
        return self.session.cookies.get("oauth_token_secret", domain=self.domain)

    def _request(self, get, url, **kwargs):
        if kwargs.get("auth", "") != False:
            if self.oauth_token:
                oauth = OAuth1(self.apiParams["oAuthKey"], self.apiParams["oAuthSecret"],
                               resource_owner_key=self.oauth_token,
                               resource_owner_secret=self.oauth_token_secret,
                               signature_type="auth_header")
            else:
                oauth = OAuth1(self.apiParams["oAuthKey"], self.apiParams["oAuthSecret"], signature_type="auth_header")
            kwargs.update({"auth": oauth})
        else:
            del kwargs["auth"]
        return super()._request(get, url, **kwargs)

    def needs_authentication(self):
        if self.session.cookies.get("oauth_client_key", domain=self.domain):
            return False
        return True

    def login(self, username, password):
        r = self.session_post(self.login_api_url, data={"email": username, "password": password})
        data = r.json()
        dateFormat = "%Y-%m-%dT%H:%M:%S%z"
        expires = datetime.strptime(data["expiration_date"], dateFormat).timestamp()
        for key in ("oauth_client_key", "oauth_token", "oauth_token_secret"):
            self.session.cookies.set(key, data[key], domain=self.domain, expires=expires)
        self.key_pair = {}
        return True

    def get_media_list(self, limit=None):
        return self.search("One", limit=limit)

    def search(self, term, limit=None):
        r = self.session_get_with_key_pair(self.search_api_url.format(term, 6))
        media = []
        items = list(filter(lambda item: item["type"] == "series", r.json()["items"]))
        for item in items[:limit]:
            series_id = item["id"]
            data = self.session_get_with_key_pair(self.seasons_api_url.format(series_id=series_id)).json()
            for season in data["items"]:
                media.append(self.create_media_data(series_id, item["title"], season_id=season["id"], season_title=season["title"]))
        return media

    def update_media_data(self, media_data: dict, r=None):
        r = self.session_get_with_key_pair(self.season_api_url.format(season_id=media_data["season_id"]))
        for episode in r.json()["items"]:
            if episode["season_id"] == media_data["season_id"]:
                self.update_chapter_data(media_data, episode["id"], episode["title"], episode["episode_number"], premium=episode["is_premium_only"], special=episode["is_clip"], date=episode["episode_air_date"])

    def get_media_data_from_url(self, url):
        match = self.stream_url_regex.search(url)
        if match:
            episode_id = match.group(1)
            r = self.session_get_with_key_pair(self.single_episode_api_url.format(episode_id=episode_id))
            data = r.json()
            media_data = self.create_media_data(data["series_id"], data["series_title"], season_id=data["season_id"], season_title=data["season_title"])
            self.update_media_data(media_data, r)
            return media_data

    def get_chapter_id_for_url(self, url):
        return self.stream_url_regex.search(url).group(1)

    def get_stream_urls(self, media_data, chapter_data):
        r = self.session_get_with_key_pair(self.single_episode_api_url.format(episode_id=chapter_data["id"]))
        r = self.session_get_mem_cache(r.json()["playback"])
        streams = r.json()["streams"]
        return [streams[name][""]["url"] for name in streams if "drm" not in name and "url" in streams[name][""]]

    def download_subtitles(self, media_data, chapter_data, dir_path):

        r = self.session_get_with_key_pair(self.single_episode_api_url.format(episode_id=chapter_data["id"]))
        r = self.session_get_mem_cache(r.json()["playback"])
        subtitle_data = r.json()["subtitles"]
        for lang in subtitle_data:
            if self.settings.is_allowed_text_lang(lang, media_data):
                subtitles = subtitle_data[lang]
                r = self.session_get(subtitles["url"])
                path = os.path.join(dir_path, f"{chapter_data['id']}.{subtitles['format']}")
                with open(path, 'w') as fp:
                    iterable = iter(r.content.decode().splitlines())
                    buffer = None
                    for line in iterable:
                        if self.subtitle_regex.match(line):
                            buffer = None  # ignore blank line
                            # don't output this line
                            next(iterable)  # skip line with timestamp
                        else:
                            if buffer is not None:
                                fp.write(f"{buffer}\n")
                            buffer = line
                    fp.write(f"{buffer}\n")

        return path
