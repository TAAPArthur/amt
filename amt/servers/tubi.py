import json
import re

from bs4 import BeautifulSoup

from ..server import Server
from ..util.media_type import MediaType


class Tubi(Server):
    id = "tubi"
    media_type = MediaType.ANIME
    slow_download = True

    domain = "tubitv.com"
    base_url = f"https://{domain}"

    show_url = base_url + "/category/anime/"
    search_url = base_url + "/oz/search/{}?isKidsMode=false&useLinearHeader=true"

    stream_url_regex = re.compile(f"{domain}/(?:movies|tv-shows)/([^/]*)")
    add_series_url_regex = re.compile(f"{domain}/(?:movies|series)/([^/]*)/([^/]*)")

    def get_episode_info(self, media_data=None, url=None):
        text = self.session_get_cache(url or (self.base_url + media_data["alt_id"]), ttl=-1)
        text = text.split("window.__data=", 1)[-1].split("</script>")[0].strip()
        text = text.replace("undefined", "0")
        text = text.replace("new Date(", "").replace("\")", "\"")
        text = text[:-1]
        return json.loads(text)

    def _get_media_list_from_url(self, relative_url, limit=None):
        url = self.base_url + relative_url
        match = self.add_series_url_regex.search(url)
        if match:
            data = self.get_episode_info(url=url)
            media_id = match.group(1)
            series_info = next(filter(lambda x: x["id"] == media_id, data["video"]["byId"].values()))
            if series_info["type"] == "s":
                for season_info in series_info.get("seasons", [{}]):
                    yield self.create_media_data(id=media_id, name=series_info["title"], alt_id=relative_url, season_id=season_info["number"], lang=series_info["lang"])
            else:
                yield self.create_media_data(id=media_id, name=series_info["title"], alt_id=relative_url, lang=series_info["lang"])

    def get_media_list(self, limit=None, search_term=None, **kwargs):
        r = self.session_get_cache(self.show_url)
        soup = self.soupify(BeautifulSoup, r)
        term_parts = set(self.non_word_char_regex.split(search_term.lower())) if search_term else None
        for link in soup.findAll("a", {"class": "web-content-tile__title"})[:limit]:
            if not search_term or self.score_results(term_parts=term_parts, media_name=link.getText()):
                yield from self._get_media_list_from_url(link["href"], limit=limit)

    def search_for_media(self, term, limit=2, **kwargs):
        r = self.session_get_cache(self.show_url)
        soup = self.soupify(BeautifulSoup, r)
        for link in soup.findAll("a", {"class": "web-content-tile__title"})[:limit]:
            if term in link.getText():
                yield from self._get_media_list_from_url(link["href"], limit=limit)

    """
    def search_for_media(self, term, limit=2, **kwargs):
        referer = f"https://tubitv.com/search/{term}"
        r = self.session_get(referer)
        print(r.cookies)

        self.session_set_cookie("latest_viewed_path", f"search/{term}")
        self.session_set_cookie("deviceId", "a8650587-341f-4bbc-85e9-dd627cf36356")
        data_list = self.session_get_cache_json(self.search_url.format(term), headers={"Referer": referer})
        for data in data_list:
            label = "movies" if data["type"] == "v" else "series"
            yield from self._get_media_list_from_url(f"/{label}/{data['id']}")
    """

    def update_media_data_helper(self, media_data, **kwargs):
        data = self.get_episode_info(media_data, **kwargs)
        series_info = next(filter(lambda x: x["id"] == media_data["id"], data["video"]["byId"].values()))
        episode_number_to_id = {}
        if "seasons" in series_info and not isinstance(series_info["seasons"], int):
            season_info = next(filter(lambda x: x["number"] == media_data["season_id"], series_info["seasons"])) if "seasons" in series_info else None
            episode_number_to_id = {int(x["num"]): x["id"] for x in season_info["episodes"]}

        episodes = list(filter(lambda x: x["type"] == "v" and (not episode_number_to_id or x["id"] in episode_number_to_id.values()), data["video"]["byId"].values()))

        for episode_metadata in episodes:
            self.update_chapter_data(media_data, id=episode_metadata["id"], number=episode_metadata.get("episode_number"), title=episode_metadata["title"], lang=episode_metadata["lang"], premium=episode_metadata["needs_login"])

        if episode_number_to_id:
            last_episode_info = max(episodes, key=lambda x: int(x.get("episode_number")))
            if int(last_episode_info.get("episode_number")) != max(episode_number_to_id.keys()):
                next_id = episode_number_to_id[int(last_episode_info.get("episode_number")) + 1]
                return self.base_url + f"/tv-shows/{next_id}/"
        return None

    def update_media_data(self, media_data, **kwargs):
        url = None
        while True:
            url = self.update_media_data_helper(media_data, url=url)
            if not url:
                break

    def get_stream_urls(self, media_data, chapter_data):
        data = self.get_episode_info(media_data)
        return [[x["manifest"]["url"] for x in data["video"]["byId"][chapter_data["id"]]["video_resources"]]]

    def get_subtitle_info(self, media_data, chapter_data):
        data = self.get_episode_info(media_data)
        episode_info = next(filter(lambda x: x["id"] == chapter_data["id"], data["video"]["byId"].values()))
        for subtitles in episode_info.get("subtitles", []):
            yield subtitles["lang"], subtitles["url"], None, False

    def get_all_media_data_from_url(self, url):
        match = self.add_series_url_regex.search(url)
        relative_url = url.split(self.base_url, 2)[1]
        if match:
            return list(self._get_media_list_from_url(relative_url))
        alt_id = url.split(self.domain)[1].split("?")[0]
        data = self.get_episode_info(url=url)

        chapter_id = self.get_chapter_id_for_url(url)
        series_info = next(filter(lambda x: x["type"] == "s", data["video"]["byId"].values()))
        for season_info in series_info["seasons"]:
            if chapter_id in map(lambda x: x["id"], season_info["episodes"]):
                return [self.create_media_data(id=series_info["id"], name=series_info["title"], alt_id=alt_id, season_id=season_info.get("number"), lang=series_info["lang"])]

    def get_chapter_id_for_url(self, url):
        return self.stream_url_regex.search(url).group(1)
