import re

from bs4 import BeautifulSoup
from PIL import Image

from ..server import Server
from ..util.decoder import paste

# Improved from https://github.com/manga-py/manga-py


class GenericVizManga(Server):
    domain = "viz.com"
    base_url = "http://www.viz.com"
    login_url = base_url + "/manga/try_manga_login"
    refresh_login_url = base_url + "/account/refresh_login_links"
    login_url = base_url + "/account/try_login"
    api_chapter_data_url = base_url + "/manga/get_manga_url?device_id=3&manga_id={}&page={}"
    wsj_subscriber_regex = re.compile(r"var is_wsj_subscriber = (\w*);")

    def get_token(self):
        auth_token = self.session_get(self.refresh_login_url)
        token = re.search(r"AUTH_TOKEN\s*=\s*\"(.+?)\"", auth_token.text)
        return token.group(1)

    def needs_authentication(self):
        r = self.session_get(self.refresh_login_url)
        soup = self.soupify(BeautifulSoup, r)
        account = soup.find("div", id="o_account-links-content")
        self.is_premium = self.wsj_subscriber_regex.search(r.text).group(1) == "true" if self.has_free_chapters else True
        return not account or account["logged_in"] == "false"

    def login(self, username, password):
        token = self.get_token()

        self.session_post(
            self.login_url,
            data={
                "login": username,
                "pass": password,
                "rem_user": 1,
                "authenticity_token": token,
            })
        return not self.needs_authentication()

    def get_media_chapter_data_helper(self, chapter_data, num_pages):

        pages = []
        for i in range(num_pages):
            pages.append(self.create_page_data(url=self.api_chapter_data_url.format(chapter_data["id"], i), ext="jpg"))
        return pages

    def save_chapter_page(self, page_data, path):
        r = self.session_get(page_data["url"], headers={"Referer": "https://www.viz.com"})
        real_img_url = r.text.strip()

        r = self.session_get(real_img_url, stream=True)

        orig = Image.open(r.raw)  # type: Image.Image
        solution = self.solve_image(orig)
        solution.save(path)

    def solve_image(self, orig: Image) -> Image.Image:
        new_size = (orig.size[0] - 90, orig.size[1] - 140)
        ref = Image.new(orig.mode, new_size)  # type: Image.Image
        ref.paste(orig)

        _key = 42016
        exif = orig.getexif()
        if _key in exif:
            key = [int(i, 16) for i in exif[_key].split(":")]
            width, height = exif[256], exif[257]
        else:
            exif_regex = re.compile(b'.+?([a-f0-9]{2}(?::[a-f0-9]{2})+)')
            exif_ = exif_regex.search(orig.info.get('exif'))
            assert exif_ is not None
            key = [int(i, 16) for i in exif_.group(1).decode().split(':')]
            width, height = exif[256], exif[257]

        small_width = int(width / 10)
        small_height = int(height / 15)

        paste(ref, orig, (
            0, small_height + 10,
            small_width, height - 2 * small_height,
        ), (
            0, small_height,
            small_width, height - 2 * small_height,
        ))

        paste(ref, orig, (
            0, 14 * (small_height + 10),
            width, orig.height - 14 * (small_height + 10),
        ), (
            0, 14 * small_height,
            width, orig.height - 14 * (small_height + 10),
        ))

        paste(ref, orig, (
            9 * (small_width + 10), small_height + 10,
            small_width + (width - 10 * small_width), height - 2 * small_height,
        ), (
            9 * small_width, small_height,
            small_width + (width - 10 * small_width), height - 2 * small_height,
        ))

        for i, j in enumerate(key):
            paste(ref, orig, (
                (i % 8 + 1) * (small_width + 10), (int(i / 8) + 1) * (small_height + 10),
                small_width, small_height,
            ), (
                (j % 8 + 1) * small_width, (int(j / 8) + 1) * small_height,
                small_width, small_height,
            ))

        return ref


class VizManga(GenericVizManga):
    id = "vizmanga"

    base_url = "http://www.viz.com"
    api_series_url = base_url + "/shonenjump"
    api_chapters_url = base_url + "/shonenjump/chapters/{}"
    api_chapter_url = base_url + "/shonenjump/{}-chapter-{}/chapter/{}"

    chapter_regex = re.compile(r"/shonenjump/(.*)-chapter-([\d\-]*)/chapter/(\d*)")

    stream_url_regex = re.compile(r"viz.com/shonenjump/([\w\-]*)-chapter-1/chapter/(\d+)")

    series_name_regex = re.compile(r"var seriesTitle\s*=\s*.([\w ]*).;")
    page_regex = re.compile(r"var pages\s*=\s*(\d*);")

    def get_media_data_from_url(self, url):
        media_id = self.stream_url_regex.search(url).group(1)
        title = self.series_name_regex.search(self.session_get(url).text).group(1)
        return self.create_media_data(id=media_id, name=title)

    def get_chapter_id_for_url(self, url):
        return self.stream_url_regex.search(url).group(2)

    def get_media_list(self, limit=None):
        r = self.session_get(self.api_series_url)

        soup = self.soupify(BeautifulSoup, r)
        divs = soup.findAll("a", {"class": "o_chapters-link"})
        result = []
        for div in divs[:limit]:
            id = div["href"].split("/")[-1]
            name = div.find("div", {"class", "pad-x-rg pad-t-rg pad-b-sm type-sm type-rg--sm type-md--lg type-center line-solid"}).getText().strip()
            result.append(self.create_media_data(id=id, name=name))

        return result

    def update_media_data(self, media_data):
        r = self.session_get(self.api_chapters_url.format(media_data["id"]))
        soup = self.soupify(BeautifulSoup, r)

        # Chapters
        chapters = soup.findAll("a", {"class": "o_chapter-container"})
        slugs = set()
        for chapter in chapters:
            raw_url_maybe = chapter["data-target-url"]
            match = self.chapter_regex.search(raw_url_maybe)
            # series_name = match.group(1)
            chapter_number = match.group(2)
            chapter_id = match.group(3)
            chapter_date = None
            premium = chapter["href"] != raw_url_maybe
            # There could be duplicate elements with the same chapter slug; they refer to the same chapter so skip them
            if chapter_id in slugs:
                continue
            slugs.add(chapter_id)
            chapter_date = None
            # chapter_date = chapter.find("td", {"class": "pad-y-0 pad-r-0 pad-r-rg--sm"}).getText()

            # There seems to be a title field in the metadata... it doesn't seem useful nor unique
            # eg "My Hero Academia: Vigilantes Chapter 1.0"
            # so we"ll just use the chapter number as the title
            title = chapter_number

            self.update_chapter_data(media_data, id=chapter_id, number=chapter_number, premium=premium, title=title, date=chapter_date)

    def get_media_chapter_data(self, media_data, chapter_data, stream_index=0):
        chapter_url = self.api_chapter_url.format(media_data["id"], str(chapter_data["number"]).replace(".", "-"), chapter_data["id"])
        match = self.page_regex.search(self.session_get(chapter_url).text)
        num_pages = int(match.group(1)) + 1
        return self.get_media_chapter_data_helper(chapter_data, num_pages)


class VizMangaLibrary(GenericVizManga):
    id = "vizmanga_lib"
    alias = "vizmanga"
    progress_volumes = True
    has_free_chapters = False

    base_url = "http://www.viz.com"
    list_series_url = base_url + "/account/library"
    stream_url_regex = re.compile(r"viz.com/read/manga/(([^/]*(?=-volume))(-volume[^/]*)?)/product/([^/]*)/digital")

    volume_id_regex = re.compile(r"var mangaCommonId\s*=\s*(\d*)\s*;")
    volume_number_regex = re.compile(r"var volumeNumber\s*=\s*(\d*)\s*;")
    page_regex = re.compile(r" (\d+) pages")

    def _get_media_list_helper(self, volumes=False, media_name=None, media_id=None):
        r = self.session_get(self.list_series_url)
        soup = self.soupify(BeautifulSoup, r)
        for table in soup.findAll("table", {"class": "product-table"}):
            td = table.findAll("td", {"class": "product-table--primary"})
            name, url = td[0].getText(), td[1].find("a")["href"]
            slug = self.stream_url_regex.search(self.base_url + url).group(2)
            if (media_name == None and media_id == None) or media_name == name or media_id == slug:
                if not volumes:
                    yield self.create_media_data(id=slug, name=name)
                else:
                    yield url

    def get_media_list(self, limit=None):
        return list(self._get_media_list_helper())[:limit]

    def update_media_data(self, media_data):
        for url in self._get_media_list_helper(True, media_data["name"]):
            r = self.session_get(self.base_url + url)
            match = self.volume_id_regex.search(r.text)
            volume_id = match.group(1)
            match = self.volume_number_regex.search(r.text)
            volume_number = match.group(1)
            match = self.page_regex.search(r.text)
            num_pages = int(match.group(1)) + 1
            self.update_chapter_data(media_data, id=volume_id, title=str(volume_number), number=volume_number, premium=True, num_pages=num_pages)

    def get_media_chapter_data(self, media_data, chapter_data, stream_index=0):
        return self.get_media_chapter_data_helper(chapter_data, chapter_data["num_pages"])

    def get_media_data_from_url(self, url):
        return next(self._get_media_list_helper(media_id=self.stream_url_regex.search(url).group(1)))

    def get_chapter_id_for_url(self, url):
        return self.volume_id_regex.search(self.session_get(url).text).group(1)
