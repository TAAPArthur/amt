from bs4 import BeautifulSoup
import re

from ..server import Server
from ..util.media_type import MediaType


class Freewebnovel(Server):
    id = "freewebnovel"
    media_type = MediaType.NOVEL
    official = False

    domain = "freewebnovel.com"
    base_url = f"https://{domain}"
    media_list_url = base_url + "/most-popular-novel/"
    search_url = base_url + "/search?searchkey={}"
    chapters_url = base_url + "/{}.html"
    chapter_url = base_url + "/{}/{}.html"

    stream_url_regex = re.compile(f"{domain}/(.*)/(chapter-.*).html")

    def _get_media_helper(self, r):
        soup = self.soupify(BeautifulSoup, r)
        div = soup.find("div", {"class": "col-content"})
        media_list = []
        for series_data in div.findAll("div", {"class": "li-row"}) if div else []:
            header = series_data.find("h3", {"class": "tit"})
            if header:
                link = header.find("a")
                name = link["title"]
                media_id = link["href"].split("/")[-1].split(".htm")[0]
                media_list.append(self.create_media_data(media_id, name))
        return media_list

    def get_media_list(self, limit=None):
        return self._get_media_helper(self.session_get(self.media_list_url))

    def search_for_media(self, term, limit=None, **kwargs):
        return self._get_media_helper(self.session_get(self.search_url.format(term)))

    def _update_media_data(self, media_data, soup):
        div = soup.find("div", {"class": "m-newest2"})
        for link in div.findAll("a", {"class": "con"}):
            chapter_id = link["href"].split("/")[-1].split(".html")[0]
            title = link["title"]
            number = chapter_id.split("-")[-1]
            self.update_chapter_data(media_data, chapter_id, title, number)

    def update_media_data(self, media_data):
        r = self.session_get(self.chapters_url.format(media_data["id"]))
        soup = self.soupify(BeautifulSoup, r)
        relative_paths = soup.find("select", {"id": "indexselect"}).findAll("option")
        self._update_media_data(media_data, soup)
        for relative_path in map(lambda x: x["value"], relative_paths[1:]):
            r = self.session_get_cache(self.base_url + relative_path, skip_cache=relative_path == relative_paths[-1])
            soup = self.soupify(BeautifulSoup, r)
            self._update_media_data(media_data, soup)

    def get_media_chapter_data(self, media_data, chapter_data, **kwargs):
        url = self.chapter_url.format(media_data["id"], chapter_data["id"])
        return [self.create_page_data(url, ext="xhtml")]

    def save_chapter_page(self, page_data, path):
        r = self.session_get(page_data["url"])
        soup = self.soupify(BeautifulSoup, r)
        text = str(soup.find("div", {"class": "txt"}))

        with open(path, "w") as fp:
            fp.write(text)

    def get_chapter_id_for_url(self, url):
        return self.stream_url_regex.search(url).group(2)

    def get_media_data_from_url(self, url):
        media_id = self.stream_url_regex.search(url).group(1)
        r = self.session_get(self.chapters_url.format(media_id))
        soup = self.soupify(BeautifulSoup, r)
        name = soup.find("h1", "tit").getText().strip()
        return self.create_media_data(media_id, name)
