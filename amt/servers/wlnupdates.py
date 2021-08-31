import re
from time import sleep

from bs4 import BeautifulSoup

from ..server import NOVEL, Server


class WLN_Updates(Server):
    id = "wlnupdates"
    media_type = NOVEL
    extension = "xhtml"
    api_url = "https://www.wlnupdates.com/api"
    stream_url_regex = re.compile(r"wlnupdates.com/series-id/(\d*)/")
    number_in_chapter_url_regex = re.compile(r"(\d+[-\.]?\d*)")
    chapter_number_in_chapter_url_regex = re.compile(r"chapter-(\d+)")
    part_number_in_chapter_url_regex = re.compile(r"part-(\d+)")
    part_number_alt_in_chapter_url_regex = re.compile(r"-(\d)\d*$")

    known_sources = {1781: ("Asian Hobbyist", lambda soup: ((e["value"], float(e.getText().split()[-1]), e.getText()) for e in soup.find("select", {"name": "chapter"}).findAll("option")))}

    def get_media_list(self, limit=None):
        r = self.session_post("https://www.wlnupdates.com/api", json={"mode": "search-advanced", "series-type": {"Translated": "included"}})
        return [self.create_media_data(x["id"], x["title"]) for x in r.json()["data"][:limit]]

    def search(self, term, limit=None):
        r = self.session_post("https://www.wlnupdates.com/api", json={"title": term, "mode": "search-title"})
        return [self.create_media_data(x["sid"], x["match"][0][1]) for x in r.json()["data"]["results"][:limit]]

    def get_media_data_from_url(self, url):
        sid = self.stream_url_regex.search(url).group(1)
        media_data = self.create_media_data(sid, "")
        self.update_media_data(media_data)
        return media_data

    def session_post(self, url, **kwargs):
        r = super().session_post(url, **kwargs)
        for i in range(self.settings.max_retires):
            if not r.json()["error"]:
                break
            sleep(1)
            r = super().session_post(url, **kwargs)
        return r

    def update_media_data(self, media_data):
        r = self.session_post("https://www.wlnupdates.com/api", json={"id": media_data["id"], 'mode': 'get-series-data'})
        visted_chapters = set()
        data = r.json()["data"]
        if not media_data.get("name", None):
            media_data["name"] = data["title"]
        sources = {}
        sample_url = {}

        for chapter in data["releases"]:
            translation_id = chapter["tlgroup"]["id"]
            if translation_id in self.known_sources:
                sources[translation_id] = sources.get(translation_id, 0) + 1
                sample_url[translation_id] = chapter["srcurl"]

        for source in sorted(sources.keys(), key=lambda x: sources[x], reverse=True):
            soup = self.soupify(BeautifulSoup, self.session_get(sample_url[source]))
            translation_group_name, func = self.known_sources[source]
            for slug, number, title in func(soup):
                if number not in visted_chapters:
                    self.update_chapter_data(media_data, id=f"{number}-{source}", number=number, title=f"{translation_group_name} {title}", alt_id=slug)
                    visted_chapters.add(number)

        for chapter in data["releases"]:
            if chapter["srcurl"] and chapter["chapter"] and chapter["tlgroup"]["id"] not in self.known_sources:
                formatted_srcurl = chapter["srcurl"][:-1] if chapter["srcurl"][-1] == "/" else chapter["srcurl"]
                title = formatted_srcurl.split("/")[-1]
                number = float(chapter["chapter"])
                source = chapter["tlgroup"]["id"]
                if number not in visted_chapters:
                    visted_chapters.add(number)
                    self.update_chapter_data(media_data, id=f"{number}-{source}", number=number, alt_id=chapter["srcurl"], title=title)

    def get_media_chapter_data(self, media_data, chapter_data):
        return [self.create_page_data(url=chapter_data["alt_id"])]

    def save_chapter_page(self, page_data, path):
        r = self.session_get(page_data["url"])
        soup = self.soupify(BeautifulSoup, r)
        p = soup.find_all("p")
        with open(path, 'w') as fp:
            fp.write("<?xml version='1.0' encoding='UTF-8'?>\n")
            fp.write("<html><body>\n")
            for paragraph in p:
                text = self.settings.auto_replace_if_enabled(paragraph.getText(), media_data=page_data["media_data"])
                fp.write(f"<p>{text}</p>\n")
            fp.write("</body></html>")
