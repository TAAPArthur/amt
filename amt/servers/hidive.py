import atexit
import os
import re

from bs4 import BeautifulSoup

from ..server import Server
from ..util.media_type import MediaType


class Hidive(Server):
    id = "hidive"
    media_type = MediaType.ANIME
    has_free_chapters = False

    base_url = "https://www.hidive.com"
    domain = "hidive.com"
    search_url = base_url + "/search?q={}"
    list_url = base_url + "/dashboard"
    login_url = base_url + "/account/login"
    episode_list_url = base_url + "/tv/{}"
    episode_list_pattern = "/stream/{}/(s.*e(.*))"

    episode_data_url = base_url + "/play/settings"

    stream_url_regex = re.compile(domain + r"/stream/([^/]*)/([^/]*)")
    add_series_url_regex = re.compile(f"(?:{domain}|^)/(?:tv|movies)/([^/]*)")
    logo_regex = re.compile(r"https://static.hidive.com/bumpers/hidive/subscriber/HIDIVE_Bumper11_LogoIntroPremium_\d*p.ts")

    def needs_authentication(self):
        r = self.session_get(self.base_url)
        soup = self.soupify(BeautifulSoup, r)
        return soup.find("a", class_="user-label") is None

    @property
    def is_premium(self):
        cached_id = self.session_get_cookie("CacheId")
        if cached_id and cached_id.count("0") == len(cached_id.strip()):
            return False
        return self.session_get_cookie("UserStatus") is not None

    def login(self, username, password):
        r = self.session_get(self.login_url)
        soup = self.soupify(BeautifulSoup, r)
        form = soup.find("form", {"id": "form-login"})
        data = {}
        for input_elements in form.findAll("input"):
            data[input_elements["name"]] = input_elements.get("value", "")
        data["Email"] = username
        data["Password"] = password
        self.session_post(self.base_url + form["action"], data=data)
        return not self.needs_authentication()

    def find_links_from_url(self, url, regex):
        r = self.session_get(url)
        soup = self.soupify(BeautifulSoup, r)
        for link in soup.findAll("a"):
            href = link.get("data-playurl", "") or link.get("href", "")
            match = regex.search(href)
            if match:
                yield link, match

    def _get_media_list(self, url, regex):
        media_data = []
        seen_ids = set()
        for link, match in self.find_links_from_url(url, regex):
            media_id = match.group(1)
            title = link.get("data-title") or link.getText().strip()
            if title and media_id not in seen_ids:
                media_data.append(self.create_media_data(id=media_id, name=title))
                seen_ids.add(media_id)
        return media_data

    def get_media_list(self, **kwargs):
        return self._get_media_list(self.list_url, self.stream_url_regex)

    def search_for_media(self, term, alt_id=None, **kwargs):
        return self._get_media_list(self.search_url.format(term), self.add_series_url_regex)

    def update_media_data(self, media_data: dict, r=None, **kwargs):
        regex = re.compile(self.episode_list_pattern.format(media_data["id"]))
        for link, match in self.find_links_from_url(self.episode_list_url.format(media_data["id"]), regex):
            parent = link.parent.parent.parent.parent
            element = parent.find(lambda x: x.getText().strip() and (x.get("data-original-title") or x.get("title")))
            if element:
                title = element.get("data-original-title") or element.get("title")
                self.update_chapter_data(media_data, id=match.group(1), number=match.group(2), title=title, premium=True)

    def get_media_chapter_data(self, media_data, chapter_data, **kwargs):
        referer = f"https://www.hidive.com/stream/{media_data['id']}/chapter_data['id']"
        headers = dict(headers={"Referer": referer})
        page_data = super().get_media_chapter_data(media_data, chapter_data, **kwargs)
        [page.update(headers) for page in page_data]
        return page_data

    def get_episode_info(self, media_data, chapter_data):
        return self.session_get_cache_json(self.episode_data_url, mem_cache=True, post=True, data={"Title": media_data["id"], "Key": chapter_data["id"], "PlayerId": "f4f895ce1ca713ba263b91caeb1daa2d08904783"})

    def get_stream_urls(self, media_data, chapter_data):
        data = self.get_episode_info(media_data, chapter_data)
        urls = []
        for stream_data in data["renditions"].values():
            urls.append([stream_data["bitrates"]["hls"]])
        return urls

    def prepare_stream(self, media_data, chapter_data, urls):
        urls_to_stream = []
        for url in urls:
            ext = self.get_extension(url)
            if ext != "m3u8":
                return url
            dir_path = os.path.join(self.settings.get_chapter_dir(media_data, chapter_data), ".tmp")
            os.makedirs(dir_path, exist_ok=True)
            m = self.get_m3u8_info(url)
            playlist = sorted(m.playlists, key=lambda x: x.stream_info.bandwidth, reverse=True)
            r = self.session_get(playlist[0].uri)
            name = os.path.join(dir_path, chapter_data["id"])
            atexit.register(lambda: os.unlink(name))
            match = self.logo_regex.search(r.text)
            logo_url = match.group(0)
            assert logo_url in r.text, r.text[:255]
            with open(name, 'w') as fp:
                fp.write(r.text.replace(logo_url, ""))
            urls_to_stream.append(name)
        return urls if not urls_to_stream else [logo_url] + urls_to_stream

    def get_subtitle_info(self, media_data, chapter_data):
        data = self.get_episode_info(media_data, chapter_data)
        for stream_data in data["renditions"].values():
            for lang, _, url, _ in stream_data["ccFiles"]:
                yield lang, url, None, True

    def get_media_data_from_url(self, url):
        media_id = self._get_media_id_from_url(url)
        r = self.session_get(url)
        soup = self.soupify(BeautifulSoup, r)
        title = soup.find("div", {"class": "episodes"}).find("h1").getText().strip()
        return self.create_media_data(id=media_id, name=title)

    def get_chapter_id_for_url(self, url):
        return self.stream_url_regex.search(url).group(2)
