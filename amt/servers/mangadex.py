import re

from ..server import Server


class SafeDict(dict):
    def __missing__(self, key):
        return '{' + key + '}'


class Mangadex(Server):
    id = "mangadex"
    official = False

    api_base_url = "https://api.mangadex.org"
    domain = "mangadex.org"

    list_url = api_base_url + "/manga?limit={limit}&offset={offset}"
    search_url = api_base_url + "/manga?title={title}&limit={limit}&offset={offset}"
    manga_chapters_url = api_base_url + "/chapter?manga={}&limit=100&offset={}"
    server_url = api_base_url + "/at-home/server/{}"
    chapter_url = api_base_url + "/chapter/{}"

    manga_url = api_base_url + "/manga/{}"
    stream_url_regex = re.compile(r"mangadex.org/chapter/([^/]*)")

    def _get_media_list(self, data, target_lang=None):
        results = []
        for result in data:
            attributes = result["attributes"]
            for lang in attributes["availableTranslatedLanguages"]:
                if not target_lang or target_lang == lang:
                    results.append(self.create_media_data(id=result["id"], name=list(result["attributes"]["title"].values())[0], lang=lang))
        return results

    def _list_or_search_get_media_list(self, url, limit=100):
        offset = 0
        while True:
            r = self.session_get(url.format(limit=min(limit or 100, 100), offset=offset))
            data = r.json()
            yield from self._get_media_list(data["data"])
            offset += data["limit"]
            if offset >= data["total"] or (limit and offset > limit):
                break

    def get_media_list(self, limit=100, **kwargs):
        yield from self._list_or_search_get_media_list(self.list_url, limit)

    def search_for_media(self, term, limit=100, **kwargs):
        return list(self._list_or_search_get_media_list(self.search_url.format_map(SafeDict(title=term)), limit))

    def get_media_data_from_url(self, url):
        chapter_id = self.stream_url_regex.search(url).group(1)
        chapter_data = self.session_get(self.chapter_url.format(chapter_id)).json()
        relationships = chapter_data["data"]["relationships"]
        lang = chapter_data["data"]["attributes"]["translatedLanguage"]
        for metadata in relationships:
            if metadata["type"] == "manga":
                data = self.session_get(self.manga_url.format(metadata["id"])).json()
                return self._get_media_list((data["data"], ), target_lang=lang)[0]

    def get_chapter_id_for_url(self, url):
        return self.stream_url_regex.search(url).group(1)

    def update_media_data(self, media_data):

        offset = 0
        while True:
            r = self.session_get(self.manga_chapters_url.format(media_data["id"], offset))
            data = r.json()

            for chapter_data in sorted(data["data"], key=lambda x: x["attributes"]["publishAt"], reverse=True):
                attr = chapter_data["attributes"]
                if attr["translatedLanguage"] == media_data["lang"]:
                    if attr["pages"]:
                        self.update_chapter_data(media_data, id=chapter_data["id"], number=attr["chapter"], title=attr["title"], volume_number=attr.get("volume"))
            offset += data["limit"]
            if offset > data["total"]:
                break

    def get_media_chapter_data(self, media_data, chapter_data, stream_index=0):
        r = self.session_get(self.server_url.format(chapter_data["id"]))
        data = r.json()
        h = data["chapter"]["hash"]
        formats = ["data", "dataSaver"][stream_index]
        pages = data["chapter"][formats]
        base_url = r.json()["baseUrl"]
        return [self.create_page_data(url="{}/data/{}/{}".format(base_url, h, page)) for page in pages]
