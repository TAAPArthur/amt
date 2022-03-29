import re

from ..server import Server


class Mangadex(Server):
    id = "mangadex"
    official = False

    api_base_url = "https://api.mangadex.org"

    list_url = api_base_url + "/manga?limit={}"
    search_url = api_base_url + "/manga?title={}&limit={}"
    manga_chapters_url = api_base_url + "/chapter?manga={}&limit=100&offset={}"
    server_url = api_base_url + "/at-home/server/{}"
    chapter_url = api_base_url + "/chapter/{}"

    manga_url = api_base_url + "/manga/{}"
    stream_url_regex = re.compile(r"mangadex.org/chapter/([^/]*)/")

    def _get_media_list(self, data):
        results = []
        for result in data:
            results.append(self.create_media_data(id=result["id"], name=list(result["attributes"]["title"].values())[0]))
        return results

    def get_media_list(self, limit=100):
        r = self.session_get(self.list_url.format(limit if limit else 0))
        return self._get_media_list(r.json()["data"])

    def search_for_media(self, term, limit=100):
        r = self.session_get(self.search_url.format(term, limit if limit else 0))
        return self._get_media_list(r.json()["data"])

    def get_media_data_from_url(self, url):
        chapter_id = self.stream_url_regex.search(url).group(1)

        relationships = self.session_get(self.chapter_url.format(chapter_id)).json()["data"]["relationships"]
        for metadata in relationships:
            if metadata["type"] == "manga":
                data = self.session_get(self.manga_url.format(metadata["id"])).json()
                return self.create_media_data(id=data["data"]["id"], name=list(data["data"]["attributes"]["title"].values())[0])

    def get_chapter_id_for_url(self, url):
        return self.stream_url_regex.search(url).group(1)

    def update_media_data(self, media_data):

        offset = 0
        visited_chapter_numbers = set()
        while True:
            r = self.session_get(self.manga_chapters_url.format(media_data["id"], offset))
            data = r.json()

            for chapter_data in sorted(data["data"], key=lambda x: x["attributes"]["publishAt"], reverse=True):
                attr = chapter_data["attributes"]
                if self.settings.is_allowed_text_lang(attr["translatedLanguage"], media_data):
                    if attr["pages"] and attr["chapter"] not in visited_chapter_numbers:
                        visited_chapter_numbers.add(attr["chapter"])
                        self.update_chapter_data(media_data, id=chapter_data["id"], number=attr["chapter"], title=attr["title"])
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
