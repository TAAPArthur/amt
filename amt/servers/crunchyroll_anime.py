import re

from ..server import ANIME
from .crunchyroll import Crunchyroll


class CrunchyrollAnime(Crunchyroll):
    id = 'crunchyroll_anime'

    api_base_url = 'http://api.crunchyroll.com'
    search_series = api_base_url + "/list_series.0.json?media_type=anime&session_id={}&filter=prefix:{}"
    list_media = api_base_url + "/list_media.0.json?media_type=anime&session_id={}&series_id={}"
    stream_url = api_base_url + "/info.0.json?fields=media.stream_data&locale=enUS&session_id={}&media_id={}"
    bandwidth_regex = re.compile(r"BANDWIDTH=([0-9]*),")
    series_url = api_base_url + "/list_collections.0.json?media_type=anime&session_id={}&series_id={}"
    media_type = ANIME

    extension = "ts"

    def get_media_list(self):
        return self.search("a")

    def search(self, term):
        r = self.session_get(self.search_series.format(self.get_session_id(), term))
        data = r.json()["data"]
        media_data = []
        for item in data[:5]:
            r = self.session_get(self.series_url.format(self.get_session_id(), item["series_id"]))
            season_data = r.json()["data"]
            season_number_to_name_id_list = {}
            for season in season_data:
                season_number = season["season"]
                if season_number in season_number_to_name_id_list:
                    season_number_to_name_id_list[season_number][0] = "{} S{}".format(item['name'], season_number)
                    season_number_to_name_id_list[season_number][1].append(season["collection_id"])
                else:
                    season_number_to_name_id_list[season_number] = [season["name"], [season["collection_id"]], season_number]
            for name, season_id_list, season_number in season_number_to_name_id_list.values():
                media_data.append(self.create_media_data(id=item['series_id'], name=item['name'], season_ids=season_id_list, season_number=season_number))

        return media_data

    def update_media_data(self, media_data: dict):
        r = self.session_get(self.list_media.format(self.get_session_id(), media_data["id"]))
        data = r.json()["data"]
        for chapter in data:
            if chapter['episode_number'] and chapter["collection_id"] in media_data["season_ids"]:
                self.update_chapter_data(media_data, id=chapter['media_id'], number=chapter['episode_number'], title=chapter['name'], premium=not chapter["free_available"])

    def get_stream_url(self, media_data, chapter_data):
        r = self.session_get(self.stream_url.format(self.get_session_id(), chapter_data["id"]))
        stream = r.json()["data"]["stream_data"]["streams"][0]

        return stream["url"]

    def get_media_chapter_data(self, media_data, chapter_data):
        r = self.session_get(self.get_stream_url(media_data, chapter_data))

        bandwidth = None
        url_bandwidth_tuples = []
        for line in r.text.splitlines():
            if line.startswith("#"):
                match = self.bandwidth_regex.search(line)
                if match:
                    bandwidth = match.group(1)
            elif line:
                url_bandwidth_tuples.append((bandwidth, line))
        url_bandwidth_tuples.sort()

        m3u8_url = url_bandwidth_tuples[0][1]
        r = self.session_get(m3u8_url)
        return [self.create_page_data(url=line) for line in r.text.splitlines() if not line.startswith("#")]

    def save_chapter_page(self, page_data, path):
        r = self.session_get(page_data["url"])
        with open(path, 'wb') as fp:
            fp.write(r.content)
