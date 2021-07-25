import re

from ..server import Server

RE_ENCRYPTION_KEY = re.compile(".{1,2}")


class Mangaplus(Server):
    id = "mangaplus"
    lang = "en"
    language = "english"
    sync_removed = True

    base_url = "https://mediaplus.shueisha.co.jp"
    api_url = "https://jumpg-webapi.tokyo-cdn.com/api"
    api_search_url = api_url + "/title_list/all?format=json"
    api_media_url = api_url + "/title_detail?title_id={0}&format=json"
    api_chapter_url = api_url + "/manga_viewer?chapter_id={0}&split=yes&img_quality=high&format=json"
    media_url = base_url + "/titles/{0}?format=json"

    stream_url_regex = re.compile(r"mangaplus.shueisha.co.jp/viewer/(\d+)")

    def get_media_data_from_url(self, url):
        chapter_id = self.get_chapter_id_for_url(url)
        r = self.session_get(self.api_chapter_url.format(chapter_id))
        series_info = r.json()["success"]["mangaViewer"]
        return self.create_media_data(id=series_info["titleId"], name=series_info["titleName"])

    def get_chapter_id_for_url(self, url):
        return self.stream_url_regex.search(url).group(1)

    def get_media_list(self):
        return self.search("")

    def search(self, term):
        term = term.lower()
        results = []
        r = self.session_get(self.api_search_url)
        for series in r.json()["success"]["allTitlesView"]["titles"]:
            if series.get("language", "ENGLISH") == self.language.upper() and term in series["name"].lower():
                results.append(self.create_media_data(id=series["titleId"], name=series["name"]))
        return results

    def update_media_data(self, media_data):
        r = self.session_get(self.api_media_url.format(media_data["id"]))
        series_info = r.json()["success"]["titleDetailView"]
        for chapter in series_info["firstChapterList"] + series_info.get("lastChapterList", []):
            try:
                number = int(chapter["name"][1:] if chapter["name"][0] == "#" else chapter["name"])
            except ValueError:
                number = 0
            self.update_chapter_data(media_data, id=chapter["chapterId"], title=chapter["subTitle"], number=number)

    def get_media_chapter_data(self, media_data, chapter_data):
        r = self.session_get(self.api_chapter_url.format(chapter_data["id"]))
        return [self.create_page_data(url=page["mangaPage"]["imageUrl"], encryption_key=page["mangaPage"]["encryptionKey"]) for page in r.json()["success"]["mangaViewer"]["pages"] if "mangaPage" in page]

    def save_chapter_page(self, page_data, path):
        r = self.session_get(page_data["url"])

        if page_data["encryption_key"] is not None:
            # Decryption
            key_stream = [int(v, 16) for v in RE_ENCRYPTION_KEY.findall(page_data["encryption_key"])]
            block_size_in_bytes = len(key_stream)

            content = bytes([int(v) ^ key_stream[index % block_size_in_bytes] for index, v in enumerate(r.content)])
        else:
            content = r.content

        with open(path, "wb") as fp:
            fp.write(content)
