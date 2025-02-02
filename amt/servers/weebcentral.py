from ..server import Server
from bs4 import BeautifulSoup
import re


class Weebcentral(Server):
    id = "weebcentral"
    official = False

    domain = "weebcentral.com"
    base_url = f"https://{domain}"

    search_url = base_url + "/search/data?order=Ascending&official=Any&display_mode=Full+Display"
    manga_url = base_url + "/series/{}"
    chapter_url = base_url + "/chapters/{}"
    images_url = base_url + "/chapters/{}/images?is_prev=False&reading_style=long_strip"

    add_series_url_regex = re.compile(domain + r"/series/([A-Z0-9]+)")
    stream_url_regex = re.compile(domain + r"/chapters/([^/]+)")

    def update_media_data(self, media_data, **kwargs):
        r = self.session_get(self.manga_url.format(media_data["id"]))
        soup = self.soupify(BeautifulSoup, r)
        for a_element in reversed(soup.select("a")):
            title_element = a_element.select_one("span.flex > span")
            if not title_element:
                continue
            title = title_element.text.strip()
            num = title.split(" ")[-1]  # chapter number theoretically is at end of chapter title
            self.update_chapter_data(media_data, a_element.get("href").split("/")[-1], title, number=num)

    def get_media_chapter_data(self, media_data, chapter_data, **kwargs):
        r = self.session_get(
            self.images_url.format(chapter_data["id"]),
            headers={
                "Hx-Current-Url": self.chapter_url.format(chapter_data["id"]),
                "Hx-Request": "true",
                "Referer": self.chapter_url.format(chapter_data["id"]),
            }
        )
        soup = self.soupify(BeautifulSoup, r)
        pages = []
        for element in soup.select('img'):
            pages.append(self.create_page_data(element.get('src')))
        return pages

    def search_for_media(self, term, **kwargs):
        sort_param = "Best Match" if term else "Alphabet"
        r = self.session_get(
            self.search_url + f"&sort={sort_param}&text={term}",
            headers={
                "Hx-Current-Url": f"{self.base_url}/search",
                "Hx-Request": "true",
                "Hx-Target": "search-results",
                "Hx-Trigger": "advanced-search-form",
                "Referer": f"{self.base_url}/search",
            }
        )
        soup = self.soupify(BeautifulSoup, r)
        for a_element in soup.select("a"):
            url = a_element.get("href")
            name = a_element.text.strip()
            if not "\n" in name and self.can_add_media_from_url(url):
                slug = self._get_media_id_from_url(url)
                media_data = self.create_media_data(slug, name=name)
                yield media_data

    def get_chapter_id_for_url(self, url):
        return self.stream_url_regex.search(url).group(1)

    def get_media_data_from_url(self, url):
        r = self.session_get(url)
        soup = self.soupify(BeautifulSoup, r)
        if self.can_stream_url(url):
            for a_element in soup.select("a"):
                url = a_element.get("href")
                name = a_element.text.strip()
                if not "\n" in name and self.can_add_media_from_url(url):
                    return self.get_media_data_from_url(url)

        name = soup.find("title").text.split(" | ")[0]
        slug = self._get_media_id_from_url(url)
        return self.create_media_data(slug, name=name)
