import json
import re

from collections import defaultdict
from datetime import datetime
from requests_oauthlib import OAuth1

from ..server import Server
from ..util.media_type import MediaType


class Vrv(Server):
    #id = "vrv"
    home = "https://vrv.co/"
    media_type = MediaType.ANIME
    stream_url_regex = re.compile(r"vrv.\w+/watch/(\w*)/.+")

    api_param_regex = re.compile(r"window.__APP_CONFIG__\s*=\s*(.*);")
    api_state_regex = re.compile(r"window.__INITIAL_STATE__\s*=\s*(.*);")

    domain = "vrv.co"
    api_base = "https://api.vrv.co"
    login_api_url = api_base + "/core/authenticate/by:credentials"
    key_pair_url = api_base + "/core/index"

    _search_api_url = None
    _season_api_url = None
    _seasons_api_url = None
    _single_episode_api_url = None
    _apiParams = None
    key_pair = None

    @property
    def is_premium(self):
        return self._is_logged_in

    def _load_urls(self):
        if not self.key_pair:
            r = self.session_get(self.key_pair_url)
            data = r.json()
            d = defaultdict(dict)
            for item in data["signing_policies"]:
                d[item["path"]][item["name"]] = item["value"]
            self.key_pair = {path.replace("*", ".*"): "&".join([f"{k}={v}" for k, v in d[path].items()]) for path in d}
            url_ptr = data["__links__"]["cms_index.v2"]["href"]
            links = self.session_get_with_key_pair(self.api_base + url_ptr + "?")["__links__"]
            self._single_episode_api_url = self.api_base + links["episode"]["href"] + "?"
            self._season_api_url = self.api_base + links["episodes"]["href"].replace("{?", "?season_id={")
            self._seasons_api_url = self.api_base + links["seasons"]["href"].replace("{?", "?series_id={")
            self._search_api_url = self.api_base + links["search_results"]["href"] + "?q={}&n={}"

            url_ptr_v1 = data["__links__"]["disc_index"]["href"]
            links = self.session_get_with_key_pair(url_ptr_v1 + "?")["__links__"]
            self._list_api_url = self.api_base + links["browse"]["href"] + "?sort_by=popularity&start=0&n={}"

    @property
    def list_api_url(self):
        self._load_urls()
        return self._list_api_url

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
                return self.session_get_cache_json(url, mem_cache=True)
        assert False
        return self.session_get_cache_json(url, mem_cache=True)

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

    def update_default_args(self, kwargs):
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

    def get_media_list_helper(self, url, limit):
        item_data = self.session_get_with_key_pair(url)
        media = []
        items = list(filter(lambda item: item["type"] == "series", item_data["items"]))
        for item in items[:limit]:
            series_id = item["id"]
            data = self.session_get_with_key_pair(self.seasons_api_url.format(series_id=series_id))
            for season in data["items"]:
                media.append(self.create_media_data(series_id, item["title"], season_id=season["id"], season_title=season["title"], lang=None))
        return media

    def get_media_list(self, limit=2, **kwargs):
        return self.get_media_list_helper(self.list_api_url.format(limit if limit is not None else 2), limit)

    def search_for_media(self, term, limit=6, **kwargs):
        return self.get_media_list_helper(self.search_api_url.format(term, limit), limit)

    def update_media_data(self, media_data: dict, r=None):
        data = self.session_get_with_key_pair(self.season_api_url.format(season_id=media_data["season_id"]))
        for episode in data["items"]:
            if episode["season_id"] == media_data["season_id"]:
                self.update_chapter_data(media_data, episode["id"], episode["title"], episode["episode_number"], premium=episode["is_premium_only"], special=episode["is_clip"], date=episode["episode_air_date"])

    def get_media_data_from_url(self, url):
        match = self.stream_url_regex.search(url)
        if match:
            episode_id = match.group(1)
            data = self.session_get_with_key_pair(self.single_episode_api_url.format(episode_id=episode_id))
            media_data = self.create_media_data(data["series_id"], data["series_title"], season_id=data["season_id"], season_title=data["season_title"])
            return media_data

    def get_chapter_id_for_url(self, url):
        return self.stream_url_regex.search(url).group(1)

    def get_stream_urls(self, media_data, chapter_data):
        data = self.session_get_with_key_pair(self.single_episode_api_url.format(episode_id=chapter_data["id"]))
        streams = self.session_get_cache_json(data["playback"], mem_cache=True)["streams"]
        results = []
        for soft_sub in (True, False):
            for name in streams:
                if "drm" in name:
                    continue
                for key in streams[name]:
                    valid_lang = (key == "") == soft_sub
                    if valid_lang and "url" in streams[name][key] and "manifest.mpd" not in streams[name][key]["url"]:
                        results.append([streams[name][key]["url"]])
        return results

    def get_subtitle_info(self, media_data, chapter_data):
        data = self.session_get_with_key_pair(self.single_episode_api_url.format(episode_id=chapter_data["id"]))
        subtitle_data = self.session_get_cache_json(data["playback"], mem_cache=True)["subtitles"]
        for lang, subtitles in subtitle_data.items():
            yield lang, subtitles["url"], subtitles["format"], True
