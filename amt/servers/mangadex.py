import re

from ..server import Server


class Mangadex(Server):
    id = "mangadex"
    extension = "png"

    api_base_url = "https://api.mangadex.org"

    list_url = api_base_url + "/manga?limit=100"
    search_url = api_base_url + "/manga?title={}"
    manga_chapters_url = api_base_url + "/chapter?manga={}&limit=100&offset={}"
    server_url = api_base_url + "/at-home/server/{}"
    chapter_url = api_base_url + "/chapter/{}"

    manga_url = api_base_url + "/manga/{}"
    stream_url_regex = re.compile(r"mangadex.org/chapter/([^/]*)/")

    def _get_media_list(self, data):
        results = []
        for result in data:
            results.append(self.create_media_data(id=result["data"]["id"], name=list(result["data"]["attributes"]["title"].values())[0]))
        return results

    def get_media_list(self):
        r = self.session_get(self.list_url)
        return self._get_media_list(r.json()["results"])

    def search(self, term):
        r = self.session_get(self.search_url.format(term))
        return self._get_media_list(r.json()["results"])

    def get_media_data_from_url(self, url):
        chapter_id = self.stream_url_regex.search(url).group(1)

        relationships = self.session_get(self.chapter_url.format(chapter_id)).json()["relationships"]
        for metadata in relationships:
            if metadata["type"] == "manga":
                return self._get_media_list([self.session_get(self.manga_url.format(metadata["id"])).json()])[0]

    def get_chapter_id_for_url(self, url):
        return self.stream_url_regex.search(url).group(1)

    def update_media_data(self, media_data):

        offset = 0
        chapterNumberToPublishDate = {}
        while True:
            r = self.session_get(self.manga_chapters_url.format(media_data["id"], offset))
            data = r.json()
            for chapter in data["results"]:
                chapter_data = chapter["data"]
                attr = chapter_data["attributes"]
                if attr["translatedLanguage"] == self.settings.getLanguageCode(self.id):
                    if attr["chapter"] in chapterNumberToPublishDate:
                        if chapterNumberToPublishDate[attr["chapter"]] < attr["publishAt"]:
                            continue
                        else:
                            del media_data["chapters"][chapterNumberToPublishDate[attr["chapter"]]]
                    chapterNumberToPublishDate[attr["chapter"]] = attr["publishAt"]
                    self.update_chapter_data(media_data, id=chapter_data["id"], number=attr["chapter"], title=attr["title"])
            offset += data["limit"]
            if offset > data["total"]:
                break

    def get_media_chapter_data(self, media_data, chapter_data):
        r = self.session_get(self.server_url.format(chapter_data["id"]))
        base_url = r.json()["baseUrl"]
        attr = self.session_get(self.chapter_url.format(chapter_data["id"])).json()["data"]["attributes"]
        return [self.create_page_data(url="{}/data/{}/{}".format(base_url, attr["hash"], page)) for page in attr["data"]]
