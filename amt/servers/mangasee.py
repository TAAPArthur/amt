import json
import re

import cloudscraper

from ..server import Server


class Mangasee(Server):
    id = "mangasee"
    official = False

    base_url = "https://mangasee123.com"
    media_list_url = base_url + "/_search.php"
    manga_url = base_url + "/manga/{0}"
    chapter_url = base_url + "/read-online/{0}-chapter-{1}-page-1.html"
    chapter_url_n = base_url + "/read-online/{0}-chapter-{1}-index-{2}-page-1.html"
    page_url = "https://{}/manga/{}/{}-{:03d}.png"

    chapter_regex = re.compile(r"vm.Chapters = (.*);")
    page_regex = re.compile(r"vm.CurChapter = (.*);")
    domain_regex = re.compile(r"vm.CurPathName\w* = \"(.*)\";")
    stream_url_regex = re.compile(r"mangasee123.com/read-online/(.*)-chapter-(\d*\.?\d?)-page")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.session = cloudscraper.create_scraper(sess=self.session, browser={
            'browser': 'firefox',
            'platform': 'linux',
            'desktop': True
        })

    def get_media_data_from_url(self, url):
        media_id = self.stream_url_regex.search(url).group(1)
        for media_data in self.get_media_list():
            if media_data["id"] == media_id:
                return media_data

    def get_chapter_id_for_url(self, url):
        chapter_num = float(self.stream_url_regex.search(url).group(2))
        media_data = self.get_media_data_from_url(url)
        self.update_media_data(media_data)
        for chapter_data in media_data["chapters"].values():
            if chapter_data["number"] == chapter_num:
                return chapter_data["id"]

    def get_media_list(self):
        r = self.session_get(self.media_list_url)
        data = r.json()
        return [self.create_media_data(media_data["i"], media_data["s"]) for media_data in data]

    def update_media_data(self, media_data):
        r = self.session_get(self.manga_url.format(media_data["id"]))
        match = self.chapter_regex.search(r.text)
        chapters_text = match.group(1)
        chapter_list = json.loads(chapters_text)
        for chapter in chapter_list:
            id = chapter["Chapter"]
            number = float(id[1:-1] + "." + id[-1])
            self.update_chapter_data(media_data, id, str(number), number)

    def get_media_chapter_data(self, media_data, chapter_data):
        r = self.session_get(self.chapter_url.format(media_data["id"], chapter_data["number"]))
        match = self.page_regex.search(r.text)
        if not match:
            for i in range(1, 10):
                r = self.session_get(self.chapter_url_n.format(media_data["id"], chapter_data["number"], i))
                match = self.page_regex.search(r.text)
                if match:
                    break
        page_text = match.group(1)
        page_data = json.loads(page_text)
        match = self.domain_regex.search(r.text)
        domain = match.group(1)

        pages = []
        for i in range(int(page_data["Page"])):
            number_str = "{:04d}".format(int(chapter_data["number"])) if chapter_data["number"] % 1 == 0 else "{:06.1f}".format(chapter_data["number"])
            pages.append(self.create_page_data(url=self.page_url.format(domain, media_data["id"], number_str, i + 1)))
        return pages

    def save_chapter_page(self, page_data, path):
        r = self.session_get(page_data["url"])
        if r.status_code == 200:
            with open(path, "wb") as fp:
                fp.write(r.content)
