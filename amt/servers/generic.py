
from bs4 import BeautifulSoup

from ..server import Server
from ..util.media_type import MediaType
from urllib.parse import urlparse,parse_qs
import re


class GenericNovel(Server):
    id = "generic_novel"
    media_type = MediaType.NOVEL
    official = False

    add_series_url_regex = re.compile(r"\?.*amt_parser=(.*),(.*)")

    def get_media_list(self, **kwargs):
        return []

    def get_media_data_from_url(self, url):
        parser = parse_qs(urlparse(url).query)["amt_parser"][0]
        key, value = parser.split(",")
        parser_map = {key: value}
        domain = urlparse(url).netloc
        return self.create_media_data(url, name=urlparse(url).path[1:], alt_id=urlparse(url).path[1:], parser_map=parser_map, domain=domain)

    def update_media_data(self, media_data, limit=None, **kwargs):
        r = self.session_get_cache(media_data["id"])
        soup = self.soupify(BeautifulSoup, r)
        content = soup.find("div", media_data["parser_map"])
        links = content.findAll("a")
        i = 0
        for link in links:
            href = link["href"]
            if media_data["domain"] in href  and href != media_data["id"]:
                i= i + 1
                chapter_id = urlparse(href).path[1:]
                title = link.getText()
                if not chapter_id :
                    continue
                self.update_chapter_data(media_data, chapter_id, title, number=i)

    def get_media_chapter_data(self, media_data, chapter_data, **kwargs):
        url = "https://" + media_data["domain"] + "/" + chapter_data["id"]
        return [self.create_page_data(url, ext="xhtml", parser_map=media_data["parser_map"])]


    def save_chapter_page(self, page_data, path):
        r = self.session_get_cache(page_data["url"])
        soup = self.soupify(BeautifulSoup, r)
        content = soup.find("div", page_data["parser_map"])
        text = self.download_external_sources_and_transform_text(str(content), path)

        with open(path, "w") as fp:
            fp.write(text)
