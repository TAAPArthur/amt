import os
import re
from shlex import quote

from ..server import ANIME
from .crunchyroll import GenericCrunchyrollServer


class CrunchyrollAnime(GenericCrunchyrollServer):
    id = "crunchyroll_anime"

    api_base_url = "http://api.crunchyroll.com"
    search_series = api_base_url + "/list_series.0.json?media_type=anime&session_id={}&filter=prefix:{}"
    list_media = api_base_url + "/list_media.0.json?limit=2000&media_type=anime&session_id={}&series_id={}"
    stream_url = api_base_url + "/info.0.json?fields=media.stream_data&locale=enUS&session_id={}&media_id={}"
    episode_url = api_base_url + "/info.0.json?session_id={}&media_id={}"
    bandwidth_regex = re.compile(r"BANDWIDTH=([0-9]*),")
    series_url = api_base_url + "/list_collections.0.json?media_type=anime&session_id={}&series_id={}"
    media_type = ANIME

    stream_url_regex = re.compile(r"https://www.crunchyroll.com/([^/]*)/.*-(\d+)$")

    extension = "ts"

    def _create_media_data(self, series_id, item_alt_id, season_id=None):
        r = self.session_get(self.series_url.format(self.get_session_id(), series_id))
        season_data = r.json()["data"]
        unique_seasons = len(set(map(lambda x: x["season"], season_data))) == len(season_data)
        for season in season_data:
            if not season_id or season["collection_id"] == season_id:
                yield self.create_media_data(id=series_id, name=season["name"], season_id=season["collection_id"], season_title=season["season"] if unique_seasons else season["collection_id"], dir_name=item_alt_id)

    def search(self, term):
        r = self.session_get(self.search_series.format(self.get_session_id(), term.replace(" ", "%20")))
        data = r.json()["data"]
        media_data = []
        for item in data:
            item_alt_id = item["url"].split("/")[-1]
            media_data += list([media for media in self._create_media_data(item["series_id"], item_alt_id)])

        return media_data

    def update_media_data(self, media_data: dict):
        r = self.session_get(self.list_media.format(self.get_session_id(), media_data["id"]))
        data = r.json()["data"]
        for chapter in data:
            if chapter["collection_id"] == media_data["season_id"] and not chapter["clip"]:
                special = False
                if not chapter["episode_number"]:
                    special = True
                    chapter["episode_number"] = 0
                elif chapter["episode_number"][-1].isalpha():
                    special = True
                    chapter["episode_number"] = chapter["episode_number"][:-1]

                self.update_chapter_data(media_data, id=chapter["media_id"], number=chapter["episode_number"], title=chapter["name"], premium=not chapter["free_available"], special=special)

    def get_media_data_from_url(self, url):

        match = self.stream_url_regex.match(url)
        media_name_hint = match.group(1)
        # media_name_prefix_hint = media_name_hint.split("-")[0]
        chapter_id = match.group(2)
        r = self.session_get(self.episode_url.format(self.get_session_id(), chapter_id))
        data = r.json()["data"]
        media_data = next(self._create_media_data(data["series_id"], media_name_hint, season_id=data["collection_id"]))
        self.update_media_data(media_data)
        assert chapter_id in media_data["chapters"]
        return media_data

    def get_chapter_id_for_url(self, url):
        chapter_id = url.split("-")[-1]
        return chapter_id

    def get_stream_urls(self, media_data=None, chapter_data=None, url=None):
        chapter_id = url.split("-")[-1] if url else chapter_data["id"]

        r = self.session_get(self.stream_url.format(self.get_session_id(), chapter_id))
        stream = r.json()["data"]["stream_data"]["streams"][0]

        r = self.session_get(stream["url"])
        bandwidth = None
        url_bandwidth_tuples = []
        for line in r.text.splitlines():
            if line.startswith("#"):
                match = self.bandwidth_regex.search(line)
                if match:
                    bandwidth = int(match.group(1))
            elif line:
                url_bandwidth_tuples.append((bandwidth, line))
        url_bandwidth_tuples.sort(reverse=True)
        url_bandwidth_tuples.append((0, stream["url"]))

        return map(lambda x: x[1], url_bandwidth_tuples)

    def post_download(self, media_data, chapter_data, dir_path):
        pathWithoutExt = os.path.join(dir_path, chapter_data["id"])
        self.settings.convert(self.extension, f"{quote(dir_path)}/*.{self.extension}", pathWithoutExt)

    def get_stream_data(self, media_data, chapter_data):
        import m3u8
        assert media_data["media_type"] == ANIME
        m3u8_url = self.get_stream_url(media_data=media_data, chapter_data=chapter_data)
        return [self.create_page_data(url=segment.uri, encryption_key=segment.key) for segment in m3u8.load(m3u8_url).segments]

    def get_media_chapter_data(self, media_data, chapter_data):
        return self.get_stream_data(media_data, chapter_data)
