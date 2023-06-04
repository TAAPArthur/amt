from bs4 import BeautifulSoup
import re

from ..util.media_type import MediaType
from .torrent import GenericTorrentServer


def category_to_media_type(cat):
    if "1_" in cat:
        return MediaType.ANIME
    else:  # 3_
        return MediaType.NOVEL | MediaType.MANGA


def media_type_to_category(media_type):
    if not media_type:
        return ""
    elif media_type & MediaType.ANIME:
        return "1_2"
    else:
        return "3_1"


class Nyaa(GenericTorrentServer):
    id = "nyaa"
    domain = "nyaa.si"
    base_url = f"https://{domain}"
    search_url = base_url + "/?s=size&o=desc&f=0&c={}&q={}"
    torrent_url = base_url + "/download/{}.torrent"

    stream_url_regex = re.compile(r"nyaa.si/view/(\w*)")
    media_type = MediaType.ANIME | MediaType.NOVEL | MediaType.MANGA

    def get_media_list(self, **kwargs):
        return self.search_for_media("", **kwargs)

    def search_for_media(self, term, media_type=None, **kwargs):
        category = media_type_to_category(media_type)
        r = self.session_get(self.search_url.format(category, term))
        soup = self.soupify(BeautifulSoup, r)
        table = soup.find("table", {"class": "torrent-list"})
        results = []
        row_num_to_media_type = {}
        for row_num, row, link in ((row_num, row, link) for row_num, row in enumerate(table.findAll("tr")) for link in row.findAll("a")) if table else []:
            if link["href"].startswith("/?c="):
                row_num_to_media_type[row_num] = category_to_media_type(link["href"].split("=", 2)[1])
            elif link["href"].startswith("/view/") and not link["href"].endswith("#comments"):
                slug = link["href"].split("/")[-1]
                title = link["title"]
                label = " ".join(filter(lambda x: x, map(lambda x: x.getText().strip(), row.findAll("td", {"class": "text-center"}))))
                media_type = row_num_to_media_type[row_num]
                results.append(self.create_media_data(id=slug, name=title, label=label, torrent_file=self.torrent_url.format(slug), media_type=media_type))
        return results

    def get_media_data_from_url(self, url):
        slug = self.stream_url_regex.search(url).group(1)
        r = self.session_get(url)
        soup = self.soupify(BeautifulSoup, r)
        title = soup.find("h3", class_="panel-title").getText().strip()
        for link in soup.findAll("a"):
            if link["href"].startswith("/?c="):
                media_type = category_to_media_type(link["href"].split("=", 2)[1])
                break
        return self.create_media_data(id=slug, name=title, media_type=media_type, torrent_file=self.torrent_url.format(slug))
