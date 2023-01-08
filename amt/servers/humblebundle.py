import json
import re

from requests.exceptions import HTTPError

from ..server import Server
from ..util.media_type import MediaType
from ..util.name_parser import (get_media_id_from_name,
                                get_number_from_file_name)
from ..util.progress_type import ProgressType


class HumbleBundle(Server):
    id = "humblebundle"
    need_to_login_to_list = True
    media_type = MediaType.MANGA | MediaType.NOVEL
    progress_type = ProgressType.VOLUME_ONLY
    official = True
    has_free_chapters = False
    is_premium = True
    need_cloud_scraper = True

    domain = "humblebundle.com"
    base_url = "https://www.humblebundle.com/home/library"
    login_url = "https://www.humblebundle.com/processlogin"
    meida_info_url = "https://www.humblebundle.com/api/v1/order/{}?all_tpkds=true"
    game_key_regex = re.compile(r'"gamekeys": (\[[^\]]+\])')

    stream_url_regex = re.compile(r"dl.humble.com/(\w*).\s*?gamekey=(\w*)")

    media_name_regex = re.compile("(Vol\.|volume|Volume|Part|) \d+\.?\d*$")

    def get_all_bundle_keys(self):
        match = self.game_key_regex.search(self.session_get_cache(self.base_url))
        return json.loads(match.group(1)) if match else []

    def get_media_of_type(self, key, platform="ebook"):
        data = self.session_get_cache_json(self.meida_info_url.format(key))
        for product in data["subproducts"]:
            id = product["machine_name"]
            name = product["human_name"]
            for downloads in filter(lambda x: x["platform"] == platform, product["downloads"]):
                download_struct = downloads["download_struct"]
                media_name = self.media_name_regex.split(name)[0].strip()
                media_id = get_media_id_from_name(media_name)
                yield key, media_id, media_name, id, name, download_struct

    def get_all_media_of_type(self, platform="ebook"):
        for key in self.get_all_bundle_keys():
            yield from self.get_media_of_type(key, platform="ebook")

    def _get_media_list_helper(self, media_metadata_tuples, chapter_id_filter=None):
        media_list = {}
        for key, media_id, media_name, chapter_id, name, download_struct in media_metadata_tuples:
            if chapter_id_filter and chapter_id != chapter_id_filter:
                continue
            maybe_manga = bool(list(filter(lambda x: x["name"] == "CBZ", download_struct)))
            if media_id not in media_list:
                media_type = MediaType.MANGA if maybe_manga else MediaType.NOVEL
                media_list[media_id] = self.create_media_data(id=media_id, name=media_name, key=key, media_type=media_type)
        return list(media_list.values())

    def get_media_list(self, **kwargs):
        return self._get_media_list_helper(self.get_all_media_of_type())

    def update_media_data(self, media_data):
        for key, media_id, _, chapter_id, name, _ in self.get_media_of_type(media_data["key"]):
            if media_id == media_data["id"]:
                self.update_chapter(media_data, chapter_id, title=name, number=get_number_from_file_name(name, media_name=media_data["name"], default_num=1))

    def get_stream_urls(self, media_data, chapter_data):
        for key, media_id, name, download_struct in self.get_media_of_type(media_data["key"]):
            if media_id == chapter_data["id"]:
                return list(map(lambda x: [x["url"]["web"]], download_struct))

    def get_media_data_from_url(self, url):
        match = self.stream_url_regex.search(url)
        chapter_id, key = match.group(1), match.group(2)
        return self._get_media_list_helper(self.get_media_of_type(key, chapter_id_filter=chapter_id))[0]

    def get_chapter_id_for_url(self, url):
        return self.stream_url_regex.search(url).group(1)

    def needs_authentication(self):
        cookie = self.session_get_cookie("hbflash")
        return not cookie or "signed" not in cookie

    def login(self, username, password):
        r = self.session_get("https://www.humblebundle.com/login")

        csrf_cookie = r.cookies.get("csrf_cookie") or self.session.cookies.get("csrf_cookie")
        assert csrf_cookie

        headers = {"CSRF-Prevention-Token": csrf_cookie}

        data = dict(access_token="", access_token_provider_id="", goto="/", qs="", username=username, password=password)
        try:
            self.session_post(self.login_url, data=data, headers=headers)
        except HTTPError as e:
            r = e.response
            if r.status_code != 401 or "humble_guard_required" not in r.json():
                raise
            code = self.settings.get_prompt_for_input("Please enter coded that should have been emailed to you: ")
            data["guard"] = code
            self.session_post(self.login_url, data=data, headers=headers)
        return True
