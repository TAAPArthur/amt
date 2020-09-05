import re

from ..server import ANIME
from .crunchyroll import Crunchyroll


class CrunchyrollAnime(Crunchyroll):
    id = 'crunchyroll_anime'
    alias = Crunchyroll.id

    api_base_url = 'http://api.crunchyroll.com'
    search_series = api_base_url + "/list_series.0.json?media_type=anime&session_id={}&filter=prefix:{}"
    list_media = api_base_url + "/list_media.0.json?limit=2000&media_type=anime&session_id={}&series_id={}"
    stream_url = api_base_url + "/info.0.json?fields=media.stream_data&locale=enUS&session_id={}&media_id={}"
    bandwidth_regex = re.compile(r"BANDWIDTH=([0-9]*),")
    series_url = api_base_url + "/list_collections.0.json?media_type=anime&session_id={}&series_id={}"
    media_type = ANIME

    stream_url_regex = re.compile(r"https://www.crunchyroll.com/([^/]*)/.*-(\d+)$")

    extension = "ts"

    def get_media_list(self):
        return self.search("a")

    def search(self, term, alt_id=None):
        r = self.session_get(self.search_series.format(self.get_session_id(), term.replace(" ", "%20")))
        data = r.json()["data"]
        media_data = []
        for item in data:
            item_alt_id = item["url"].split("/")[-1]
            if alt_id and alt_id != item_alt_id:
                continue
            r = self.session_get(self.series_url.format(self.get_session_id(), item["series_id"]))
            season_data = r.json()["data"]
            unique_seasons = len(set(map(lambda x: x["season"], season_data))) == len(season_data)
            for season in season_data:
                media_data.append(self.create_media_data(id=item['series_id'], name=season["name"], season_ids=[season["collection_id"]], season_number=season["season"] if unique_seasons else season["collection_id"], dir_name=item_alt_id))

        return media_data

    def update_media_data(self, media_data: dict):
        r = self.session_get_cache(self.list_media.format(self.get_session_id(), media_data["id"]))
        data = r.json()["data"]
        for chapter in data:
            if chapter["collection_id"] in media_data["season_ids"] and not chapter['clip']:
                special = False
                if not chapter['episode_number']:
                    special = True
                    chapter['episode_number'] = 0
                elif chapter['episode_number'][-1].isalpha():
                    special = True
                    chapter['episode_number'] = chapter['episode_number'][:-1]

                self.update_chapter_data(media_data, id=chapter['media_id'], number=chapter['episode_number'], title=chapter['name'], premium=not chapter["free_available"], special=special)

    def can_stream_url(self, url):
        return self.stream_url_regex.match(url)

    def get_media_data_from_url(self, url):

        match = self.stream_url_regex.match(url)
        media_name_hint = match.group(1)
        media_name_prefix_hint = media_name_hint.split("-")[0]
        chapter_id = match.group(2)
        media_list = self.search(media_name_prefix_hint, media_name_hint) or self.search(media_name_prefix_hint[0], media_name_hint)
        for media_data in media_list:
            self.update_media_data(media_data)
            if chapter_id in media_data["chapters"]:
                return media_data

    def is_url_for_known_media(self, url, known_media):
        chapter_id = url.split("-")[-1]
        for media in known_media.values():
            if chapter_id in media["chapters"]:
                return media, media["chapters"][chapter_id]
        return False

    def get_stream_url(self, media_id=None, chapter_id=None, url=None, raw=False):
        if url:
            chapter_id = url.split("-")[-1]
        r = self.session_get(self.stream_url.format(self.get_session_id(), chapter_id))
        stream = r.json()["data"]["stream_data"]["streams"][0]
        if raw:
            return stream["url"]

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
        return url_bandwidth_tuples[0][1]

    def get_media_chapter_data(self, media_data, chapter_data):
        m3u8_url = self.get_stream_url(chapter_id=chapter_data["id"])
        r = self.session_get(m3u8_url)
        return [self.create_page_data(url=line) for line in r.text.splitlines() if not line.startswith("#")]

    def save_chapter_page(self, page_data, path):
        r = self.session_get(page_data["url"])
        with open(path, 'wb') as fp:
            fp.write(r.content)
