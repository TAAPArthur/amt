from bs4 import BeautifulSoup
import re

from ..server import Server


class Webtoons(Server):
    id = "webtoons"
    domain = "webtoons.com"
    base_url = "https://www.webtoons.com"
    search_url = base_url + "/en/search?keyword={}"
    list_series_url = base_url + "/top"
    chapters_url = base_url + "/episodeList?titleNo={}"
    stream_url_regex = re.compile(domain + r".*/viewer\?title_no=(\d*)\&episode_no=(\d*)")
    add_series_url_regex = re.compile(domain + r".*?title_no=(\d*)")

    url_split_regex = re.compile(r"title(?:_n|N)o=(\d*)")

    def get_media_data_from_element(self, element, media_id=None):
        genreElement = element.find(class_="genre")
        nameElement = element.find(class_="subj")
        if not genreElement or not nameElement:
            assert not media_id
            return None
        if not media_id:
            href = element.find("a").get("href")
            match = self.url_split_regex.search(href)
            media_id = match.group(1)
        return self.create_media_data(id=media_id, name=nameElement.getText().strip(), genre=genreElement.getText().strip())

    def get_media_list_helper(self, elements):
        media_list = []
        for element in elements:
            media_data = self.get_media_data_from_element(element)
            if media_data:
                media_list.append(media_data)
        return media_list

    def get_media_list(self, limit=None):
        r = self.session_get(self.list_series_url)
        soup = self.soupify(BeautifulSoup, r)
        return self.get_media_list_helper(soup.find("ul", class_="lst_type1").find_all("li"))

    def search_for_media(self, term, limit=None):
        r = self.session_get(self.search_url.format(term))
        soup = self.soupify(BeautifulSoup, r)
        element = soup.find("ul", class_="card_lst")
        return self.get_media_list_helper(element.find_all("li")) if element else []

    def update_media_data(self, media_data):
        if not media_data.get("url"):
            r = self.session_get(self.chapters_url.format(media_data["id"]))
            soup = self.soupify(BeautifulSoup, r)
            href = soup.find("a", {"id": "_btnEpisode"})
            media_data["url"] = href.get("href")
        r = self.session_get(media_data["url"])
        soup = self.soupify(BeautifulSoup, r)
        element = soup.find("div", {"class": "episode_lst"})
        for li in element.findAll("li"):
            chapter_number = li.get("data-episode-no")
            chapter_title = li.find("span", {"class": "subj"})
            self.update_chapter_data(media_data, id=chapter_number, number=chapter_number, title=chapter_title)

    def get_media_chapter_data(self, media_data, chapter_data, stream_index=0):
        r = self.session_get(media_data["url"])
        soup = self.soupify(BeautifulSoup, r)
        element = soup.find("div", {"id": "_imageList"})
        pages = []
        for img in element.findAll("img"):
            pages.append(self.create_page_data(url=img.get("src")))
        return pages

    def get_chapter_id_for_url(self, url):
        return self.stream_url_regex.search(url).group(2)

    def get_media_data_from_url(self, url):
        media_id = self._get_media_id_from_url(url)
        r = self.session_get(self.chapters_url.format(media_id))
        soup = self.soupify(BeautifulSoup, r)
        element = soup.find("div", {"class": "info"})
        return self.get_media_data_from_element(element, media_id=media_id)
