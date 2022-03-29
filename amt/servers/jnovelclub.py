import logging
import os
import re
import shutil
import time

from requests.exceptions import HTTPError

from ..job import RetryException
from ..server import Server
from ..util.decoder import GenericDecoder
from ..util.media_type import MediaType


class GenericJNovelClub(Server):
    progress_volumes = True

    alias = "j_novel_club"
    login_url = "https://api.j-novel.club/api/users/login"
    api_domain = "https://labs.j-novel.club"
    api_base_url = api_domain + "/app/v1"
    user_info_url = api_base_url + "/me?format=json"

    series_info_url = api_base_url + "/series/{}?format=json"
    series_url = api_base_url + "/series?format=json"
    search_url = api_base_url + "/series?format=json"
    chapters_url = api_base_url + "/series/{}/volumes?format=json"
    pages_url = api_base_url + "/me/library/volume/{}?format=json"
    synchronize_chapter_downloads = True

    def needs_authentication(self):
        # will return 401 for invalid session and 410 for expired session
        r = self.session_get(self.user_info_url)
        self.is_premium = r.json()["level"] == "PREMIUM_MEMBER"
        return False

    def login(self, username, password):
        self.session_post(self.login_url,
                          data={
                              "email": username,
                              "password": password
                          })

        self.needs_authentication()
        return True

    def _create_media_data_helper(self, data):
        return [self.create_media_data(item["slug"], item["title"], alt_id=item["shortTitle"].replace(" ", "")) for item in data if MediaType[item["type"]] == self.media_type]

    def get_media_list(self, limit=None):
        r = self.session_get(self.series_url)
        data = r.json()["series"]
        return self._create_media_data_helper(data)[:limit]

    def search_for_media(self, term, limit=None):
        r = self.session_post(self.search_url, json={"query": term.replace(" (Manga)", ""), "type": 1 if self.media_type == MediaType.NOVEL else 2})
        data = r.json()["series"][:limit]
        return [self.create_media_data(item["slug"], item["title"], alt_id=item["shortTitle"].replace(" ", "")) for item in data]


class JNovelClub(GenericJNovelClub):
    id = "j_novel_club"
    media_type = MediaType.NOVEL
    owned_url = "https://api.j-novel.club/api/users/me?filter={'include':[{'ownedBooks':'serie'}]}"
    has_free_chapters = False

    def filter_owned_volumes(self, media_list_func):
        try:
            r = self.session_get(self.owned_url)
            media_ids = {volume["serie"] for volume in r.json()["ownedBooks"]}
        except HTTPError:
            media_ids = []
        return list(filter(lambda x: x["id"] in media_ids, media_list_func)) if media_ids else []

    def get_media_list(self, limit=None):
        return self.filter_owned_volumes(super().get_media_list)[:limit]

    def search_for_media(self, term, limit=None):
        return self.filter_owned_volumes(lambda: super().search(term=term))[:limit]

    def update_media_data(self, media_data: dict):
        r = self.session_get(self.chapters_url.format(media_data["id"]))
        for volume in r.json()["volumes"]:
            self.update_chapter_data(media_data, id=volume["legacyId"], number=volume["number"], title=volume["title"], premium=False, inaccessible=not volume["owned"])

    def get_media_chapter_data(self, media_data, chapter_data, stream_index=0):
        r = self.session_get(self.pages_url.format(chapter_data["id"]))
        return [self.create_page_data(url=r.json()["downloads"][0]["link"])]

    def save_chapter_page(self, page_data, path):
        r = self.session_get(page_data["url"], stream=True)
        with open(path, 'wb') as fp:
            fp.write(r.content)


class JNovelClubManga(JNovelClub):
    id = "j_novel_club_manga"
    alias = "j_novel_club"
    media_type = MediaType.MANGA


class GenericJNovelClubParts(GenericJNovelClub):

    part_to_series_url = JNovelClub.api_base_url + "/parts/{}/serie?format=json"
    parts_url = JNovelClub.api_base_url + "/volumes/{}/parts?format=json"
    time_to_live_sec = 3600 * 24 * 7

    def update_media_data(self, media_data: dict):
        r = self.session_get(self.chapters_url.format(media_data["id"]))

        for chapter_data in media_data["chapters"].values():
            chapter_path = self.settings.get_chapter_dir(media_data, chapter_data, skip_create=True)
            if os.path.exists(chapter_path) and (time.time() - os.path.getmtime(chapter_path)) > self.time_to_live_sec:
                shutil.rmtree(chapter_path)
        volumes = r.json()["volumes"]
        for i, volume in enumerate(volumes):
            part_data = self.session_get_cache_json(self.parts_url.format(volume["slug"]), skip_cache=i == len(volumes) - 1)
            parts = part_data["parts"]

            volume_number = volume["number"]

            total = volume["totalParts"] if volume["totalParts"] else len(parts)
            for part in parts:
                number = round(volume_number + (part["number"] - parts[0]["number"] + 1) / total - 1, 2)
                self.update_chapter_data(media_data, id=part["slug"], alt_id=part["legacyId"], number=number, title=part["title"], premium=not part["preview"])

    def get_media_chapter_data(self, media_data, chapter_data, stream_index=0):
        return [self.create_page_data(self.pages_url.format(chapter_data["alt_id"]))]

    def get_media_data_from_url(self, url):
        part_id = self.get_chapter_id_for_url(url)
        r = self.session_get(self.part_to_series_url.format(part_id))
        media_list = self._create_media_data_helper([r.json()])
        return media_list[0] if media_list else None

    def get_chapter_id_for_url(self, url):
        return self.stream_url_regex.search(url).group(1)

    def download_sources(self, resources_path, path, url, text):
        img_path = os.path.join(resources_path, os.path.basename(url).replace("%20", "_"))
        with open(img_path, 'wb') as fp:
            fp.write(self.session_get(url).content)
        text = text.replace(url, os.path.relpath(img_path, os.path.dirname(path)))
        return text

    def save_chapter_page(self, page_data, path):
        resources_path = os.path.join(os.path.dirname(path), ".resources")
        os.makedirs(resources_path, exist_ok=True)
        r = self.session_get(page_data["url"])
        text = r.text
        try:
            from bs4 import BeautifulSoup
            soup = self.soupify(BeautifulSoup, r)
            for tagName, linkField in (("img", "src"), ("link", "href")):
                for element in soup.findAll(tagName):
                    text = self.download_sources(resources_path, path, element[linkField], text)
        except ImportError:
            pass

        with open(path, 'w') as fp:
            fp.write(text)


class JNovelClubParts(GenericJNovelClubParts):
    id = "j_novel_club_parts"
    media_type = MediaType.NOVEL
    pages_url = JNovelClub.api_domain + "/embed/{}/data.xhtml"

    stream_url_regex = re.compile(r"j-novel.club/read/([\w\d\-]+)")

    def can_stream_url(self, url):
        return super().can_stream_url(url) and "-manga-" not in url


class JNovelClubMangaParts(GenericJNovelClubParts):
    id = "j_novel_club_manga_parts"
    media_type = MediaType.MANGA
    stream_url_regex = re.compile(r"j-novel.club/read/([\w\d\-]+-manga-[\w\d\-]+)")
    pages_url = JNovelClub.api_domain + "/embed/{}"

    uuid_regex = re.compile(r"data-uuid=\"([^\"]*)\"")
    token_regex = re.compile(r"data-ngtoken=\"([^\"]*)\"")

    encrypted_url = "https://m11.j-novel.club/nebel/wp/{}"

    def get_media_chapter_data(self, media_data, chapter_data, stream_index=0):
        for i in range(self.settings.max_retries):
            self.session_get("https://j-novel.club/read/{}".format(chapter_data["id"]))
            r = self.session_get(self.pages_url.format(chapter_data["alt_id"]))
            uuid = self.uuid_regex.search(r.text).group(1)
            token = self.token_regex.search(r.text).group(1)
            url = self.encrypted_url.format(uuid)
            try:
                r = self.session_post(url, data=token)
                break
            except:
                time.sleep(2)
        data = r.json()["readingOrder"]

        return [self.create_page_data(url=link["href"], encryption_key=token) for link in data]

    def save_chapter_page(self, page_data, path):
        r = self.session_get(page_data["url"], stream=True)
        max_iterations = 300 if not page_data.get("retry", False) else None
        success = GenericDecoder.descramble_and_save_img(r.raw, path, key=page_data["encryption_key"], max_iters=max_iterations)
        if not success:
            page_data["retry"] = True
            logging.debug("Failed to descramble %s", page_data["url"])
            raise RetryException(path)
