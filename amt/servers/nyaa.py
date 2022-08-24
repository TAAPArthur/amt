from bs4 import BeautifulSoup

from ..server import TorrentHelper
from ..util.media_type import MediaType


class Nyaa(TorrentHelper):
    alias = "nyaa"
    domain = "nyaa.si"
    base_url = f"https://{domain}"
    search_url = base_url + "/?s=downloads&o=desc&f=0&c={}&q={}"
    torrent_url = base_url + "/download/{}.torrent"

    def get_media_list(self, limit=10):
        return self.search_for_media("", limit=limit)

    def search_for_media(self, term, limit=10):
        r = self.session_get(self.search_url.format(self.category, term))
        soup = self.soupify(BeautifulSoup, r)
        table = soup.find("table", {"class": "torrent-list"})
        results = []
        for row, link in ((row, link) for row in table.findAll("tr") for link in row.findAll("a")) if table else []:
            if link["href"].startswith("/view/") and not link["href"].endswith("#comments"):
                slug = link["href"].split("/")[-1]
                title = link["title"]
                label = " ".join(filter(lambda x: x, map(lambda x: x.getText().strip(), row.findAll("td", {"class": "text-center"}))))
                results.append(self.create_media_data(id=slug, name=title, label=label))
                if len(results) == limit:
                    break
        return results

    def save_torrent_file(self, media_data, path):
        r = self.session_get(self.torrent_url.format(media_data["id"]))
        with open(path, 'wb') as fp:
            fp.write(r.content)


class NyaaAnime(Nyaa):
    id = "nyaa_anime"
    media_type = MediaType.ANIME
    category = "1_2"


class NyaaNovel(Nyaa):
    id = "nyaa_novel"
    media_type = MediaType.NOVEL
    category = "3_1"
