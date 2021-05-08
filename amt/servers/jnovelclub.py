import re

from ..server import MANGA, NOVEL, Server


class JNovelClub(Server):
    id = "j_novel_club"
    extension = "epub"
    media_type = NOVEL
    sync_removed = True
    progress_in_volumes = True

    stream_url_regex = re.compile(r"https://j-novel.club/series/([A-z\-])")

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

    def get_media_data_from_url(self, url):
        match = self.stream_url_regex.match(url)
        series_id = match.group(1)
        data = self.session_get(self.series_info_url.format(series_id)).json()
        return self.create_media_data(data["slug"], data["title"])

    def get_media_list(self):
        r = self.session_get(self.series_url)
        data = r.json()["series"]
        return [self.create_media_data(media_data["slug"], media_data["title"], progress_in_volumes=self.progress_in_volumes) for media_data in data if media_data["type"] == str(self.media_type)]

    def search(self, term):
        r = self.session_post(self.search_url, json={"query": term, "type": 1 if self.media_type == NOVEL else 2})
        data = r.json()["series"]
        return [self.create_media_data(media_data["slug"], media_data["title"]) for media_data in data]

    def update_media_data(self, media_data: dict):
        r = self.session_get(self.chapters_url.format(media_data["id"]))
        for volume in r.json()["volumes"]:
            self.update_chapter_data(media_data, id=volume["legacyId"], number=volume["number"], title=volume["title"], premium=False, inaccessible=not volume["owned"])

    def get_media_chapter_data(self, media_data, chapter_data):
        r = self.session_get(self.pages_url.format(chapter_data["id"]))
        return [self.create_page_data(url=r.json()["downloads"][0]["link"])]


class JNovelClubParts(JNovelClub):
    id = "j_novel_club_parts"
    alias = "j_novel_club"
    extension = "xhtml"

    parts_url = JNovelClub.api_base_url + "/volumes/{}/parts?format=json"
    pages_url = JNovelClub.api_domain + "/embed/{}/data.xhtml"
    progress_in_volumes = False

    def update_media_data(self, media_data: dict):
        r = self.session_get(self.chapters_url.format(media_data["id"]))
        for volume in r.json()["volumes"]:
            r = self.session_get(self.parts_url.format(volume["slug"]))
            for part in r.json()["parts"]:
                self.update_chapter_data(media_data, id=part["legacyId"], number=part["number"], title=part["title"], premium=not part["preview"])

    def get_media_chapter_data(self, media_data, chapter_data):
        return [self.create_page_data(self.pages_url.format(chapter_data["id"]))]


class JNovelClubManga(JNovelClub):
    id = "j_novel_club_manga"
    alias = "j_novel_club"
    media_type = MANGA