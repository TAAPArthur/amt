from ..server import Server


class Mangadex(Server):
    id = "mangadex"
    lang_name = "English"
    extension = "png"

    api_base_url = "https://api.mangadex.org"

    list_url = api_base_url + "/manga?limit=100"
    search_url = api_base_url + "/manga?title={}"
    manga_chapters_url = api_base_url + "/chapter?manga={}&limit=100&offset={}"
    server_url = api_base_url + "/at-home/server/{}"
    chapter_url = api_base_url + "/chapter/{}"

    def _get_media_list(self, data):
        results = []
        for result in data["results"]:
            results.append(self.create_media_data(id=result["data"]["id"], name=result["data"]["attributes"]["title"]["en"]))
        return results

    def get_media_list(self):
        r = self.session_get(self.list_url)
        return self._get_media_list(r.json())

    def search(self, term):
        r = self.session_get(self.search_url.format(term))
        if r.status_code == 204:
            return None
        return self._get_media_list(r.json())

    def update_media_data(self, media_data):

        offset = 0
        while True:
            r = self.session_get(self.manga_chapters_url.format(media_data["id"], offset))
            if r.status_code == 204:
                break
            data = r.json()
            for chapter in data["results"]:
                chapter_data = chapter["data"]
                attr = chapter_data["attributes"]
                self.update_chapter_data(media_data, id=chapter_data["id"], number=attr["chapter"], title=attr["title"])
            offset += data["limit"]
            if offset > data["total"]:
                break

    def get_media_chapter_data(self, media_data, chapter_data):
        r = self.session_get(self.server_url.format(chapter_data["id"]))
        base_url = r.json()["baseUrl"]
        attr = self.session_get(self.chapter_url.format(chapter_data["id"])).json()["data"]["attributes"]
        return [self.create_page_data(url="{}/data/{}/{}".format(base_url, attr["hash"], page)) for page in attr["data"]]
