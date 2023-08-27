import base64
import json
import re

from ..server import Server
from ..util.media_type import MediaType
from threading import RLock

from urllib.parse import urlencode


class GenericCrunchyrollServer(Server):
    alias = "crunchyroll"

    domain = "crunchyroll.com"
    api_auth_url = "https://api-manga.crunchyroll.com/cr_authenticate?session_id={}&version=0&format=json"
    base_url = "https://api.crunchyroll.com"
    login_url = base_url + "/login.1.json"

    _access_token = "WveH9VkPLrXvuNm"
    _access_type = "com.crunchyroll.crunchyroid"

    crunchyroll_lock = RLock()
    session_id_may_be_invalid = True

    def get_session_id(self, force=False):
        with GenericCrunchyrollServer.crunchyroll_lock:
            session_id = self.session_get_cookie("session_id")
            if force or session_id is None:
                self.session_get(f"https://{self.domain}/comics/manga")
                session_id = self.session_get_cookie("session_id")
            return session_id

    def session_get_json(self, url, mem_cache=False, skip_cache=True, **kwargs):
        query_under_lock = GenericCrunchyrollServer.session_id_may_be_invalid and "session_id" in url

        def make_request(url):
            return self.session_get_cache_json(url, mem_cache=mem_cache, skip_cache=skip_cache, **kwargs)
        session_id_regex = re.compile(r"session_id=([^&]*)")
        if query_under_lock:
            original_session_id = session_id_regex.search(url).group(1)
            with GenericCrunchyrollServer.crunchyroll_lock:
                if GenericCrunchyrollServer.session_id_may_be_invalid:
                    data = make_request(url)
                    if data.get("error", False) and data["code"] == "bad_session":
                        self.logger.error("Failed request %s %s; retrying", url, data)
                        new_session_id = self.get_session_id(force=True)
                        self.logger.info("New id %s vs %s", new_session_id, original_session_id)
                        new_url = url.replace(original_session_id, new_session_id)
                        if not mem_cache:
                            kwargs["ttl"] = 0
                        data = make_request(new_url)
                    if skip_cache:
                        GenericCrunchyrollServer.session_id_may_be_invalid = False
                    return data
                else:
                    url = url.replace(original_session_id, self.get_session_id())
        return make_request(url)

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
            self.logger.info("Error authenticating %s", data)
        return True

    def login(self, username, password):
        response = self.session_get_json(self.login_url,
                                         post=True,
                                         data={
                                             "session_id": self.get_session_id(force=True),
                                             "account": username,
                                             "password": password
                                         },
                                         headers={
                                             "referer": f"https://{self.domain}/",
                                             "origin": f"https://{self.domain}/"
                                         })
        if "data" in response:
            self._store_login_data(response)
            return True
        self.logger.debug("Login failed; response: %s", response)
        return False


class Crunchyroll(GenericCrunchyrollServer):
    id = "crunchyroll"
    maybe_need_cloud_scraper = True

    base_url = "https://www.crunchyroll.com"
    manga_url = base_url + "/comics/manga/{0}/volumes"

    alpha_list_url = base_url + "/comics/manga/alpha?group=all"
    popular_list_url = base_url + "/comics/manga"

    api_base_url = "https://api-manga.crunchyroll.com"
    api_chapter_url = api_base_url + "/list_chapter?session_id={}&chapter_id={}&auth={}"
    api_chapters_url = api_base_url + "/chapters?series_id={}"

    _api_auth_token = None
    possible_page_url_keys = ["encrypted_mobile_image_url", "encrypted_composed_image_url"]
    page_url_key = possible_page_url_keys[0]

    stream_url_regex = re.compile(r"crunchyroll.com/manga/([\w-]*)/read/(\d*\.?\d*)")
    add_series_url_regex = re.compile(r"crunchyroll.com/comics/manga/([\w-]*)")

    def get_media_data_from_url(self, url):
        name_slug = self._get_media_id_from_url(url)
        for media_data in self.get_media_list():
            if media_data["alt_id"] == name_slug:
                return media_data

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

    def get_media_list(self, **kwargs):
        media_data_map = {}
        try:
            from bs4 import BeautifulSoup
            for url in (self.alpha_list_url, self.popular_list_url):
                soup = self.soupify(BeautifulSoup, self.session_get_cache(url))
                for group_item in soup.findAll("li", {"class": "group-item"}):
                    media_id = group_item["group_id"]
                    if media_id not in media_data_map:
                        link = group_item.find("a")
                        match = self.add_series_url_regex.search(self.domain + link["href"])
                        media_data_map[media_id] = self.create_media_data(id=media_id, name=link["title"], alt_id=match.group(1), locale="enUS")
        except ImportError:
            pass

        return list(media_data_map.values())

    def update_media_data(self, media_data, **kwargs):
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

    def needs_authentication(self):
        return not self.session_get_cookie("etp_rt") or super().needs_authentication()

    def init_auth_headers(self):
        if self.session_get_cookie("etp_rt"):
            grant_type, key = 'etp_rt_cookie', 'accountAuthClientId'
        else:
            grant_type, key = 'client_id', 'anonClientId'

        config = self.get_config()
        auth_token = 'Basic ' + str(base64.b64encode(('%s:' % config['cxApiParams'][key]).encode('ascii')), 'ascii')
        headers = {'Authorization': auth_token, "Content-Type": "application/x-www-form-urlencoded"}

        auth_response = self.session_get_json(f'{self.get_api_domain()}/auth/v1/token', post=True, headers=headers, data=f'grant_type={grant_type}'.encode('ascii'))
        return {'Authorization': auth_response['token_type'] + ' ' + auth_response['access_token']}

    def get_auth_headers(self):
        if not self.auth_header:
            self.auth_header = self.init_auth_headers()
        return self.auth_header

    def _get_params(self):
        policy_response = self.session_get_json(f'{self.get_api_domain()}/index/v2', headers=self.get_auth_headers())
        cms = policy_response.get('cms_web')
        bucket = cms['bucket']
        params = {
            'Policy': cms['policy'],
            'Signature': cms['signature'],
            'Key-Pair-Id': cms['key_pair_id']
        }
        return (bucket, params)

    def get_params(self):
        if not self.params:
            self.params = self._get_params()
        return self.params

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
        bucket, params = self.get_params()
        query = urlencode(params)
        url = f"{self.get_api_domain()}/cms/v2{bucket}/episodes/{media_id}"
        data = self.session_get_cache_json(f"{self.get_api_domain()}/cms/v2{bucket}/episodes/{media_id}?{query}", key=url)

        return [self.create_media_data(id=data["series_id"],
                                       name=data["series_title"],
                                       season_id=data["season_id"], season_title=data["season_title"],
                                       lang=data["audio_locale"])]

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
        bucket, params = self.get_params()

        query = urlencode(params)
        url = f"{self.get_api_domain()}/cms/v2{bucket}/episodes/{chapter_data['id']}"
        data = self.session_get_json(f"{url}?{query}", key=url)
        stream_info_url = self.get_api_domain() + data["__links__"]["streams"]["href"]
        stream_data = self.session_get_json(f"{stream_info_url}?{query}", key=stream_info_url)
        url_list = []
        for video_type, videos in stream_data["streams"].items():
            if "drm" in video_type:
                continue
            for video_info in videos.values():
                if video_info["url"]:
                    url_list.append((self.settings.get_prefered_lang_key(media_data, lang=video_info["hardsub_locale"]), video_info["url"], video_type))
        url_list.sort()
        return map(lambda x: [x[1]], url_list)

    def get_subtitle_info(self, media_data, chapter_data):
        bucket, params = self.get_params()

        query = urlencode(params)
        url = f"{self.get_api_domain()}/cms/v2{bucket}/episodes/{chapter_data['id']}"
        data = self.session_get_json(f"{url}?{query}", key=url)
        stream_info_url = self.get_api_domain() + data["__links__"]["streams"]["href"]
        stream_data = self.session_get_json(f"{stream_info_url}?{query}", key=stream_info_url)
        for lang, values in stream_data["subtitles"].items():
            yield lang, values["url"], values["format"], False
