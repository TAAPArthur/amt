from bs4 import BeautifulSoup
import re

from ..server import Server

class Manganelo(Server):
    id = 'manganelo'
    official = False

    base_url = 'https://m.manganelo.com/'
    list_url = base_url + "/wwww"
    search_url = base_url + "/search/story/{term}"

    manga_chapters_url = "https://chapmanganelo.com/manga-{media_id}"
    alt_manga_chapters_url = "https://m.manganelo.com/manga-{media_id}"
    chapter_url = manga_chapters_url + "/chapter-{chapter_id}"

    stream_url_regex = re.compile(r"(?:m.manganelo|chapmanganelo).com/manga-([^/?]*)/chapter-([^/?]*)")
    add_series_url_regex = re.compile(r"(?:m.manganelo|chapmanganelo).com/manga-([^/?]*)")

    def get_chapter_id_for_url(self, url):
        return self.stream_url_regex.search(url).group(2)

    def get_media_data_from_url(self, url):
        media_id = self.add_series_url_regex.search(url).group(1)

        r = self.session_get(url)
        soup = self.soupify(BeautifulSoup, r)
        if self.stream_url_regex.search(url):
            div = soup.find("div", class_="panel-breadcrumb")
            for item_element in div.find_all('a'):
                if self.add_series_url_regex.search(item_element["href"]) and not self.stream_url_regex.search(item_element["href"]):
                    title = item_element["title"].strip()
                    break
        else:
            div = soup.find("div", class_="story-info-right")
            title = div.find("h1").getText()

        return self.create_media_data(id=media_id, name=title)

    def _get_media_list(self, url):
        r = self.session_get(url)
        soup = self.soupify(BeautifulSoup, r)
        for clazz in ("content-homepage-item", "search-story-item"):
            for item_element in soup.find_all('div', class_=clazz):
                slug = item_element.a.get('href').split("/manga-")[1]
                title=item_element.a.get('title').strip()
                yield self.create_media_data(id=slug, name=title)

    def get_media_list(self, **kwargs):
        yield from self._get_media_list(self.list_url)

    def search_for_media(self, term, **kwargs):
        return list(self._get_media_list(self.search_url.format(term=term.replace(" ", "_"))))

    def update_media_data(self, media_data, **kwargs):
        for url in (media_data.get("referer"), self.manga_chapters_url, self.alt_manga_chapters_url):
            if not url:
                continue
            formatted_url = url.format(media_id=media_data["id"])
            r = self.session_get(formatted_url)
            soup = self.soupify(BeautifulSoup, r)
            elements = soup.find_all('a', class_="chapter-name")
            if elements:
                for item in soup.find_all('a', class_="chapter-name"):
                    chapter_id = item["href"].split("chapter-")[-1]
                    title = item.getText()
                    self.update_chapter_data(media_data, id=chapter_id, number=chapter_id, title=title)
                media_data["referer"] = formatted_url
                break

    def get_media_chapter_data(self, media_data, chapter_data, stream_index=0):
        r = self.session_get(self.chapter_url.format(media_id=media_data["id"], chapter_id=chapter_data["id"]))
        soup = self.soupify(BeautifulSoup, r)
        div = soup.find('div', class_="container-chapter-reader")
        imgs = div.find_all('img', class_="reader-content")
        return [self.create_page_data(url=page["src"], headers={"Referer": media_data["referer"]}) for page in imgs]

