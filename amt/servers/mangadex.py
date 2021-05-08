import re

from bs4 import BeautifulSoup

from ..server import Server


class Mangadex(Server):
    id = "mangadex"
    lang_name = "English"
    extension = "png"

    base_url = "https://mangadex.org"
    api_manga_url = base_url + "/api/manga/{0}"
    api_chapter_url = base_url + "/api/chapter/{0}"
    most_populars_url = base_url + "/titles/7"
    stream_url_regex = re.compile(r"https?://mangadex.org/title/(\d*)")

    def get_media_list(self):
        r = self.session_get_cache(self.most_populars_url)
        soup = BeautifulSoup(r.text, "html.parser")
        results = []
        for element in soup.find_all("a", class_="manga_title"):
            id = element.get("href").split("/")[-2]
            name = element.text.strip()
            results.append(self.create_media_data(id=id, name=name))

        return results

    def get_media_data_from_url(self, url):
        match = self.stream_url_regex.search(url)
        if match:
            id = int(match.group(1))
            r = self.session_get_cache(self.api_manga_url.format(id))
            data = r.json()
            return self.create_media_data(id=id, name=data["manga"]["title"])
        return False

    def update_media_data(self, media_data):

        r = self.session_get_cache(self.api_manga_url.format(media_data["id"]))

        resp_data = r.json()

        known_chapter_numbers = set()
        for chapter_id, chapter in resp_data["chapter"].items():
            if self.lang_name == chapter["lang_name"]:
                if chapter["chapter"] in known_chapter_numbers:
                    continue
                known_chapter_numbers.add(chapter["chapter"])
                self.update_chapter_data(media_data, id=chapter_id, number=chapter["chapter"], title=chapter["title"])

    def get_media_chapter_data(self, media_data, chapter_data):
        r = self.session_get(self.api_chapter_url.format(chapter_data["id"]))
        resp_data = r.json()
        return [self.create_page_data(url="{0}{1}/{2}".format(resp_data["server"], resp_data["hash"], page)) for page in resp_data["page_array"]]
