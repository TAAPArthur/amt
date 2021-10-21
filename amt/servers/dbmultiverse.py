import urllib.parse

from bs4 import BeautifulSoup

from ..server import Server


class Dbmultiverse(Server):
    id = "dbmultiverse"

    base_url = "https://www.dragonball-multiverse.com"
    media_url = base_url + "/{}/chapters.html?comic=page"
    chapter_url = base_url + "/{}/chapters.html?chapter={}"
    page_url = base_url + "/{}/page-{}.html"

    def get_media_list(self, limit=None):
        r = self.session_get(self.base_url)
        soup = self.soupify(BeautifulSoup, r)
        media_list = []
        for element in soup.find("div", {"id": "langs"}).findAll("a")[:limit]:
            media_list.append(self.create_media_data(id=1, name="Dragon Ball Multiverse (DBM) " + element["title"], lang=element["href"].split("/")[1]))
        return media_list

    def update_media_data(self, media_data):
        r = self.session_get(self.media_url.format(media_data["lang"]))
        soup = self.soupify(BeautifulSoup, r)

        chapters = soup.findAll("div", {"class": "cadrelect chapters"})
        chapter_map = {int(x["ch"].replace("page", "")): x for x in chapters}
        lastest_chapter = max(chapter_map.keys())
        # Latest chapter may gain pages later so don't include it
        del chapter_map[lastest_chapter]

        for id, chapter in chapter_map.items():
            self.update_chapter_data(media_data, id=id, number=int(id), title=chapter.find("h4").getText())

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
