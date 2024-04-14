import base64
import json
import re
import time
import uuid

from ..server import Server
from ..util.media_type import MediaType
from threading import RLock


class GenericCrunchyrollServer(Server):
    alias = "crunchyroll"

    domain = "crunchyroll.com"
    base_url = f"https://www.{domain}"
    api_base = f"https://api.{domain}"
    token_url = f"{base_url}/auth/v1/token"
    login_url = token_url

    crunchyroll_lock = RLock()

    _auth_headers = None
    _auth_refresh = 0

    _BASIC_AUTH = 'Basic ' + base64.b64encode(':'.join((
        't-kdgp2h8c3jub8fn0fq',
        'yfLDfMfrYvKXh4JXS1LEI2cCqu1v5Wan',
    )).encode()).decode()

    @property
    def is_logged_in(self):
        return bool(self.refresh_token)

    @property
    def refresh_token(self):
        return self.session_get_cookie("refresh_token")

    @refresh_token.setter
    def refresh_token(self, value):
        return self.session_set_cookie("refresh_token", value)

    @property
    def is_premium(self):
        return True
        for premium_cookies_name in ["crplusctamembership", "premplusctav"]:
            if self.session_get_cookie(premium_cookies_name):
                return True
        return False

    def session_get_json(self, url, mem_cache=False, skip_cache=True, **kwargs):
        self.update_auth()

        return self.session_get_cache_json(url, mem_cache=mem_cache, skip_cache=skip_cache, **kwargs)

    def get_auth_headers(self):
        self.update_auth()
        return GenericCrunchyrollServer._auth_headers

    def get_auth_headers_str(self):
        return ",".join((f"{k}:{v}" for k, v in self.get_auth_headers().items()))

    def set_auth_info(self, data):
        GenericCrunchyrollServer._auth_headers = {"Authorization": data["token_type"] + " " + data["access_token"]}
        GenericCrunchyrollServer._auth_refresh = time.time() + data.get("expires_in", 300) - 10

    def update_auth(self):
        with GenericCrunchyrollServer.crunchyroll_lock:
            if GenericCrunchyrollServer._auth_refresh > time.time():
                return

            auth_headers = {"Authorization": GenericCrunchyrollServer._BASIC_AUTH}
            if self.refresh_token:
                data = {
                    "refresh_token": self.refresh_token,
                    "grant_type": "refresh_token",
                    "scope": "offline_access",
                }
            else:
                data = {"grant_type": "client_id"}
                auth_headers["ETP-Anonymous-ID"] = str(uuid.uuid4())

            auth_response = self.session_post(self.token_url, headers=auth_headers, data=data).json()
            self.set_auth_info(auth_response)

    def login(self, username, password):
        r = self.session_post(self.login_url,
                              data={
                                  "username": username,
                                  "password": password,
                                  "grant_type": "password",
                                  "scope": "offline_access",
                              },
                              headers={'Authorization': self._BASIC_AUTH})
        data = r.json()
        self.refresh_token = data["refresh_token"]
        self.set_auth_info(data)
        return True


class CrunchyrollAnime(GenericCrunchyrollServer):
    id = "crunchyroll_anime"
    alias = "crunchyroll"
    media_type = MediaType.ANIME
    need_cloud_scraper = True

    stream_url_regex = re.compile(r"crunchyroll.\w+/watch/(\w*)/.+")
    add_series_url_regex = re.compile(r"crunchyroll.\w+/series/(\w*)")

    version = 2

    auth_header = None
    params = None

    def upgrade_state(self, media_data):
        if media_data.get("version", 0) == 1:
            return media_data["alt_id"]

    def get_config(self):
        text = self.session_get_cache("https://www.crunchyroll.com/")
        assert "window.__APP_CONFIG__" in text, text
        return json.loads(text.split("window.__APP_CONFIG__ = ")[1].splitlines()[0][:-1].split(";")[0])

    def get_api_domain(self):
        return self.get_config()['cxApiParams']['apiDomain']

    def get_media_list(self, **kwargs):
        return self.search_for_media(None, **kwargs)

    def get_media_data_for_series(self, media_id):
        season_url = f"{self.get_api_domain()}/content/v2/cms/series/{media_id}/seasons"
        season_data = self.session_get_cache_json(f"{season_url}", key=season_url, need_auth_headers=True)
        media_list = []
        for season_info in season_data["data"]:
            for version_info in (season_info.get("versions") or [{"audio_locale": season_info["audio_locale"]}]):
                media_list.append(self.create_media_data(id=media_id, name=season_info["title"], season_id=season_info["id"], lang=version_info["audio_locale"]))
        return media_list

    def search_for_media(self, term, limit=None, **kwargs):
        url = f"{self.get_api_domain()}/content/v2/discover/search?q={term}&n=6&type=series,movie_listing"
        data = self.session_get_cache_json(f"{url}", key=url, need_auth_headers=True)
        media_list = []
        for media_info in data["data"]:
            if media_info["type"] != "series":
                continue
            for media_item in media_info["items"]:
                media_list.extend(self.get_media_data_for_series(media_item['id']))
                if limit and len(media_list) > limit:
                    break
        return media_list

    def get_all_media_data_from_url(self, url):
        match = self.add_series_url_regex.search(url)
        if match:
            return self.get_media_data_for_series(match.group(1))
        media_id = self.get_chapter_id_for_url(url)
        url = f"{self.get_api_domain()}/content/v2/cms/objects/{media_id}?rating=true&locale=en-US"
        try:
            data = self.session_get_cache_json(url, key=url, need_auth_headers=True)

            media_id = data["data"][0]["episode_metadata"]["series_id"]
            return self.get_media_data_for_series(media_id)
        except:
            return []

    def get_chapter_id_for_url(self, url):
        return self.stream_url_regex.search(url).group(1)

    def update_media_data(self, media_data, **kwargs):
        url = f"{self.get_api_domain()}/content/v2/cms/seasons/{media_data['season_id']}/episodes"
        data = self.session_get_cache_json(f"{url}?preferred_audio_language=ja-JP&locale=en-US", key=url, need_auth_headers=True)
        for chapter in data["data"]:
            for audio_info in filter(lambda x: x["audio_locale"] == media_data["lang"], chapter["versions"] or [chapter]):
                chapter_id = audio_info["guid"] if "guid" in audio_info else chapter["id"]
                self.update_chapter_data(media_data, id=chapter_id, number=chapter["episode_number"], title=chapter["title"], premium=chapter["is_premium_only"], special=chapter["is_clip"], alt_id=chapter["slug_title"])

    def get_stream_urls(self, media_data=None, chapter_data=None):
        url = f"https://cr-play-service.prd.crunchyrollsvc.com/v1/{chapter_data['id']}/console/switch/play"
        data = self.session_get_json(url, need_auth_headers=True)

        url_list = []
        for hardSubs in data["hardSubs"].values():
            url_list.append((self.settings.get_prefered_lang_key(media_data, lang=hardSubs["hlang"]), hardSubs["url"]))

        url_list.append((self.settings.get_prefered_lang_key(media_data, lang=""), data["url"]))
        url_list.sort()
        return map(lambda x: [x[1]], url_list)

    def get_subtitle_info(self, media_data, chapter_data):
        url = f"https://cr-play-service.prd.crunchyrollsvc.com/v1/{chapter_data['id']}/console/switch/play"
        data = self.session_get_json(url, need_auth_headers=True)

        for subInfo in data["subtitles"].values():
            yield subInfo["language"], subInfo["url"], subInfo["format"], False

    def get_human_url(self, media_data, chapter_data):
        return f"{self.base_url}/watch/{chapter_data['id']}/"
