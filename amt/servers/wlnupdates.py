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

    def get_media_list(self):
        r = self.session_post("https://www.wlnupdates.com/api", json={"mode": "search-advanced", "series-type": {"Translated": "included"}})
        return [self.create_media_data(x["id"], x["title"]) for x in r.json()["data"]]

    def search(self, term):
        r = self.session_post("https://www.wlnupdates.com/api", json={"title": term, "mode": "search-title"})
        return [self.create_media_data(x["sid"], x["match"][0][1]) for x in r.json()["data"]["results"]]

    def get_media_data_from_url(self, url):
        sid = self.stream_url_regex.search(url).group(1)
        media_data = self.create_media_data(sid, "")
        self.update_media_data(media_data)
        return media_data

    def session_post(self, url, **kwargs):
        super().session_post(url, **kwargs)
        r = self._request(False, url, **kwargs)
        if r.json()["error"]:
            sleep(1)
            r = super().session_post(url, **kwargs)
        return r

    def guess_chapter_number(self, name):
        match = self.chapter_number_in_chapter_url_regex.search(name)
        if match:
            part_match = self.part_number_in_chapter_url_regex.search(name) or self.part_number_alt_in_chapter_url_regex.search(name)
            return int(match[1]) + (0 if not part_match or part_match[1] == "1" else float("." + part_match[1]))

        match = self.number_in_chapter_url_regex.findall(name)
        if match:
            return float(match[-1].replace("-", "."))
        return None

    def update_media_data(self, media_data):
        r = self.session_post("https://www.wlnupdates.com/api", json={"id": media_data["id"], 'mode': 'get-series-data'})
        visted_chapters = set()
        data = r.json()["data"]
        if not media_data.get("name", None):
            media_data["name"] = data["title"]
        for chapter in data["releases"]:
            if chapter["srcurl"] and chapter["chapter"]:
                formatted_srcurl = chapter["srcurl"][:-1] if chapter["srcurl"][-1] == "/" else chapter["srcurl"]
                title = formatted_srcurl.split("/")[-1]
                number = self.guess_chapter_number(title) or float(chapter["chapter"])
                if number > 1e6 or number / float(chapter["chapter"]) > 10:
                    number = float(chapter["chapter"])
                if number not in visted_chapters:
                    visted_chapters.add(number)
                    self.update_chapter_data(media_data, id=title, number=number, alt_id=chapter["srcurl"], title=title)
        if len(media_data["chapters"]) > 2:
            sorted_list = sorted(map(lambda x: (x["number"], x["id"]), media_data["chapters"].values()))
            while True:
                if sorted_list[-1][0] - sorted_list[-2][0] > 10:
                    del media_data["chapters"][sorted_list[-1][1]]
                    sorted_list.pop()
                else:
                    break

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
