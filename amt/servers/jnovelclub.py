import os
import re
import shutil
import time

from ..server import MANGA, MEDIA_TYPES, NOVEL, Server


class GenericJNovelClub(Server):

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
        return [self.create_media_data(media_data["slug"], media_data["title"], progressVolumes=self.progressVolumes) for media_data in data if MEDIA_TYPES[media_data["type"]] == self.media_type]

    def get_media_list(self):
        r = self.session_get(self.series_url)
        data = r.json()["series"]
        return self._create_media_data_helper(data)

    def search(self, term):
        r = self.session_post(self.search_url, json={"query": term, "type": 1 if self.media_type == NOVEL else 2})
        data = r.json()["series"]
        return [self.create_media_data(media_data["slug"], media_data["title"]) for media_data in data]

    def download_sources(self, resources_path, path, url, text):
        img_path = os.path.join(resources_path, os.path.basename(url).replace("%20", "_"))
        with open(img_path, 'wb') as fp:
            fp.write(self.session_get(url).content)
        text = text.replace(url, os.path.relpath(img_path, os.path.dirname(path)))
        return text

    def save_chapter_page(self, page_data, path):
        resources_path = os.path.join(os.path.dirname(path), ".resourses")
        os.makedirs(resources_path, exist_ok=True)
        r = self.session_get(page_data["url"], stream=True)
        text = r.text
        try:
            from bs4 import BeautifulSoup
            soup = self.soupify(BeautifulSoup, r)
            for tagName, linkField in (("img", "src"), ("link", "href")):
                for element in soup.findAll(tagName):
                    text = self.download_sources(resources_path, path, element[linkField], text)
        except ImportError:
            pass

        text = self.settings.auto_replace_if_enabled(text, media_data=page_data["media_data"])
        with open(path, 'w') as fp:
            fp.write(text)


class JNovelClub(GenericJNovelClub):
    id = "j_novel_club"
    extension = "epub"
    media_type = NOVEL
    progressVolumes = True

    def update_media_data(self, media_data: dict):
        r = self.session_get(self.chapters_url.format(media_data["id"]))
        for volume in r.json()["volumes"]:
            self.update_chapter_data(media_data, id=volume["legacyId"], number=volume["number"], title=volume["title"], premium=False, inaccessible=not volume["owned"])

    def get_media_chapter_data(self, media_data, chapter_data):
        r = self.session_get(self.pages_url.format(chapter_data["id"]))
        return [self.create_page_data(url=r.json()["downloads"][0]["link"])]


class JNovelClubManga(JNovelClub):
    id = "j_novel_club_manga"
    alias = "j_novel_club"
    media_type = MANGA


class GenericJNovelClubParts(GenericJNovelClub):
    progressVolumes = False

    part_to_series_url = JNovelClub.api_base_url + "/parts/{}/serie?format=json"
    parts_url = JNovelClub.api_base_url + "/volumes/{}/parts?format=json"
    time_to_live_sec = 3600 * 24 * 7

    def update_media_data(self, media_data: dict):
        r = self.session_get(self.chapters_url.format(media_data["id"]))

        for chapter_data in media_data["chapters"].values():
            chapter_path = self.settings.get_chapter_dir(media_data, chapter_data, skip_create=True)
            if os.path.exists(chapter_path) and (time.time() - os.path.getmtime(chapter_path)) > self.time_to_live_sec:
                shutil.rmtree(chapter_path)
        for volume in r.json()["volumes"]:
            r = self.session_get(self.parts_url.format(volume["slug"]))
            parts = r.json()["parts"]

            for part in parts:
                self.update_chapter_data(media_data, id=part["slug"], alt_id=part["legacyId"], number=part["number"], title=part["title"], premium=not part["preview"])

    def get_media_chapter_data(self, media_data, chapter_data):
        return [self.create_page_data(self.pages_url.format(chapter_data["alt_id"]))]

    def get_media_data_from_url(self, url):
        part_id = self.get_chapter_id_for_url(url)
        r = self.session_get(self.part_to_series_url.format(part_id))
        media_list = self._create_media_data_helper([r.json()])
        return media_list[0] if media_list else None

    def get_chapter_id_for_url(self, url):
        return self.stream_url_regex.search(url).group(1)


class JNovelClubParts(GenericJNovelClubParts):
    id = "j_novel_club_parts"
    extension = "xhtml"
    media_type = NOVEL
    pages_url = JNovelClub.api_domain + "/embed/{}/data.xhtml"

    stream_url_regex = re.compile(r"j-novel.club/read/([\w\d\-]+)")

    def can_stream_url(self, url):
        return super().can_stream_url(url) and "-manga-" not in url
