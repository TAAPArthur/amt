import re
import urllib.parse

from bs4 import BeautifulSoup

from ..server import Server


class Dbmultiverse(Server):
    id = "dbmultiverse"

    domain = "dragonball-multiverse.com"
    base_url = "https://www.dragonball-multiverse.com"
    media_url = base_url + "/{}/chapters.html?comic=page"
    chapter_url = base_url + "/{}/chapters.html?chapter={}"
    page_url = base_url + "/{}/page-{}.html"
    stream_url_regex = re.compile(domain + r"/(\w*)/(chapters.html?.*chapter=|page-)(\d*)")

    def get_media_data_from_url(self, url):
        lang = self.stream_url_regex.search(url).group(1)
        for media_data in self.get_media_list():
            if media_data["lang"] == lang:
                return media_data

    def get_chapter_id_for_url(self, url):
        match = self.stream_url_regex.search(url)
        chapter_id_or_page_num = int(match.group(3))
        if match.group(2) == "page-":
            media_data = self.get_media_data_from_url(url)
            self.update_media_data(media_data)
            for chapter in media_data.get_sorted_chapters():
                if chapter["last_page"] >= chapter_id_or_page_num:
                    return chapter["id"]
        return str(chapter_id_or_page_num)

    def get_media_list(self, **kwargs):
        r = self.session_get(self.base_url)
        soup = self.soupify(BeautifulSoup, r)
        media_list = []
        for element in soup.find("div", {"id": "langs"}).findAll("a"):
            media_list.append(self.create_media_data(id=1, name="Dragon Ball Multiverse (DBM) " + element["title"], lang=element["href"].split("/")[1]))
        return media_list

    def update_media_data(self, media_data, **kwargs):
        r = self.session_get(self.media_url.format(media_data["lang"]))
        soup = self.soupify(BeautifulSoup, r)
        chapters = soup.findAll("div", {"class": "chapter"})
        chapter_map = {int(x["num_chapter"]): x for x in chapters}
        lastest_chapter = max(chapter_map.keys())
        # Latest chapter may gain pages later so don't include it
        del chapter_map[lastest_chapter]

        for id, chapter in chapter_map.items():
            numbers = map(lambda x: x.getText().strip(), chapter.findAll("a"))
            last_page = max(map(lambda x: int(x.split()[-1]), filter(lambda x: x, numbers)))

            self.update_chapter_data(media_data, id=id, number=int(id), title=chapter.find("h4").getText(), last_page=last_page)

    def get_media_chapter_data(self, media_data, chapter_data, stream_index=0):
        r = self.session_get(self.chapter_url.format(media_data["lang"], chapter_data["id"]))

        soup = self.soupify(BeautifulSoup, r)
        page_info = soup.find("div", {"class": "pageslist"}).findAll("img")

        for page in page_info:
            r = self.session_get(self.page_url.format(media_data["lang"], page["title"]))
            soup = self.soupify(BeautifulSoup, r)
            img = soup.find("img", {"id": "balloonsimg"})
            url = img["src"]
            ext = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["ext"][0]
            yield self.create_page_data(url=self.base_url + url, ext=ext)
