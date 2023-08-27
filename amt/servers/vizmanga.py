import re
import time

from PIL import Image
from bs4 import BeautifulSoup
from datetime import datetime, timedelta

from ..server import Server
from ..util.decoder import paste
from ..util.exceptions import ChapterLimitException
from ..util.progress_type import ProgressType

# Improved from https://github.com/manga-py/manga-py


class GenericVizManga(Server):
    domain = "viz.com"
    base_url = "https://www.viz.com"
    login_url = base_url + "/manga/try_manga_login"
    refresh_login_url = base_url + "/account/refresh_login_links"
    login_url = base_url + "/account/try_login"
    api_chapter_data_url = base_url + "/manga/get_manga_url?device_id=3&manga_id={}&pages={}"
    wsj_subscriber_regex = re.compile(r"var is_wsj_subscriber = (\w*);")

    limits_url = base_url + "/manga/auth?device_id=3&manga_id={}"

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

    def get_limit_data(self, chapter_id):
        data = self.session_get_cache_json(self.limits_url.format(chapter_id), ttl=.25)
        archive_info = data["archive_info"]
        if archive_info["next_reset_epoch"] <= time.time():
            data = self.session_get_cache_json(self.limits_url.format(chapter_id), ttl=0)
        return data["archive_info"]

    def get_media_chapter_data_helper(self, chapter_data, num_pages):
        pages = []
        page_nums = ",".join(map(str, range(num_pages)))
        r = self.session_get(self.api_chapter_data_url.format(chapter_data["id"], page_nums), headers={"Referer": f"https://{self.domain}"})
        data = r.json()
        if not data["ok"] or data["data"] == "no_auth":
            archive_info = self.get_limit_data(chapter_data["id"])
            self.logger.debug("Failed to get page info %s", archive_info["err"]["msg"])
            raise ChapterLimitException(archive_info["next_reset_epoch"], archive_info["download_limit"])
        urls = data["data"]
        for page_num, url in sorted(urls.items()):
            pages.append(self.create_page_data(url=url, ext="jpg"))
        return pages

    def save_chapter_page(self, page_data, path):
        r = self.session_get(page_data["url"], stream=True)
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

    stream_url_regex = re.compile(r"viz.com/shonenjump/([\w\-]*)-chapter-.*/chapter/(\d+)")
    add_series_url_regex = re.compile(r"viz.com/shonenjump/chapters/([\w\-]*)")

    series_name_regex = re.compile(r"var series(?:_t|T)itle\s*=\s*.([^\"]*).;")
    page_regex = re.compile(r"var pages\s*=\s*(\d*);")

    next_chapter_regexes_func = [
        (re.compile("New chapter coming on (.*)"), lambda x: datetime.strptime(x, "%b %d, %Y").timestamp()),
        (re.compile("New chapter coming on (.*)"), lambda x: datetime.strptime(x, "%B %d, %Y").timestamp()),
        (re.compile("New chapter coming in (\d+) day"), lambda x: (datetime.today() + timedelta(days=int(x))).timestamp()),
        (re.compile("New chapter coming in (\d+) hour"), lambda x: (datetime.now() + timedelta(hours=int(x))).timestamp()),
        (re.compile("New chapter coming in (\d+) min"), lambda x: (datetime.now() + timedelta(minutes=int(x))).timestamp()),
    ]

    def get_remaining_chapters(self, media_data):
        chapter_data = media_data.get_last_read_chapter() or media_data.get_last_chapter()
        if chapter_data:
            archive_info = self.get_limit_data(chapter_data["id"])
            return archive_info["num_remaining"], int(archive_info["next_reset_epoch"] - time.time())

    def get_media_data_from_url(self, url):
        media_id = self._get_media_id_from_url(url)
        title = self.series_name_regex.search(self.session_get(url).text).group(1)
        return self.create_media_data(id=media_id, name=title)

    def get_chapter_id_for_url(self, url):
        return self.stream_url_regex.search(url).group(2)

    def get_media_list(self, **kwargs):
        r = self.session_get(self.api_series_url)

        soup = self.soupify(BeautifulSoup, r)
        divs = soup.findAll("a", {"class": "o_chapters-link"})
        for div in divs:
            id = div["href"].split("/")[-1]
            name = div.find("div", {"class", "pad-x-rg pad-t-rg pad-b-sm type-sm type-rg--sm type-md--lg type-center line-solid"}).getText().strip()
            yield self.create_media_data(id=id, name=name)

    def update_media_data(self, media_data, **kwargs):
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

        element = soup.find("div", {"class": "section_future_chapter"})
        timestamp = 0
        if element:
            text_str = element.getText().strip()
            for regex, func in self.next_chapter_regexes_func:
                try:
                    match = regex.search(text_str)
                    if match:
                        date_str = match.group(1).replace("  ", " ")
                        timestamp = func(date_str)
                        break
                except ValueError:
                    continue
            else:
                assert False
        media_data["nextTimeStamp"] = timestamp

    def get_media_chapter_data(self, media_data, chapter_data, stream_index=0):
        chapter_url = self.api_chapter_url.format(media_data["id"], str(chapter_data["number"]).replace(".", "-"), chapter_data["id"])
        match = self.page_regex.search(self.session_get(chapter_url).text)
        num_pages = int(match.group(1)) + 1
        return self.get_media_chapter_data_helper(chapter_data, num_pages)


class VizMangaLibrary(GenericVizManga):
    id = "vizmanga_lib"
    alias = "vizmanga"
    need_to_login_to_list = True
    progress_type = ProgressType.VOLUME_ONLY
    has_free_chapters = False

    base_url = "http://www.viz.com"
    list_series_url = base_url + "/account/library"
    stream_url_regex = re.compile(r"viz.com/read/manga/(([^/]*(?=-volume))(-volume[^/]*)?)/product/([^/]*)/digital")

    volume_id_regex = re.compile(r"var mangaCommonId\s*=\s*(\d*)\s*;")
    volume_number_regex = re.compile(r"var volumeNumber\s*=\s*(\d*)\s*;")
    page_regex = re.compile(r" (\d+) pages")

    add_series_url_regex = re.compile(GenericVizManga.domain + "/account/library/gn/([^/]*)/([^/]*)")
    series_url = base_url + "/account/library/gn/{}/{}"

    def get_media_list(self, **kwargs):
        r = self.session_get(self.list_series_url)
        soup = self.soupify(BeautifulSoup, r)
        table = soup.find("table", {"class": "purchase-table"})
        if table:
            for link in table.findAll("a"):
                url = self.base_url + link["href"]
                match = self.add_series_url_regex.search(url)
                if match:
                    yield self.create_media_data(id=match.group(1), alt_id=match.group(2), name=link.getText())
        else:
            # Special case if there is only one volume/series
            table = soup.find("table", {"class": "product-table"})
            if table:
                for td in table.findAll("td", {"class": "product-table--primary"}):
                    name, url = td[0].getText(), td[1].find("a")["href"]
                    slug = self.stream_url_regex.search(self.base_url + url).group(2)
                    yield self.create_media_data(id=slug, name=name)

    def _update_media_data(self, url, media_id=None):
        r = self.session_get(url)
        soup = self.soupify(BeautifulSoup, r)
        table = soup.find("table", {"class": "product-table"})
        for link in table.findAll("a"):
            url = link["href"]
            match = self.stream_url_regex.search(self.base_url + url)
            if match:
                if media_id is None or media_id == match.group(2):
                    yield url

    def update_media_data(self, media_data, **kwargs):
        url = self.series_url.format(media_data["id"], media_data["alt_id"])
        for volume_url in self._update_media_data(url, media_data["id"]):
            text = self.session_get_cache(self.base_url + volume_url, ttl=-1)
            match = self.volume_id_regex.search(text)
            volume_id = match.group(1)
            match = self.volume_number_regex.search(text)
            volume_number = match.group(1)
            match = self.page_regex.search(text)
            num_pages = int(match.group(1)) + 1
            self.update_chapter_data(media_data, id=volume_id, title=str(volume_number), number=volume_number, premium=True, num_pages=num_pages)

    def get_media_chapter_data(self, media_data, chapter_data, stream_index=0):
        return self.get_media_chapter_data_helper(chapter_data, chapter_data["num_pages"])

    def get_media_data_from_url(self, url):
        match = self.add_series_url_regex.search(url)
        if match:
            media_id = match.group(1)
        else:
            request_text = self.session_get_cache(url)
            media_id = re.search("/read/manga/([^/]*)/all", request_text).group(1)
        for media_data in self.get_media_list():
            if media_data["id"] == media_id:
                return media_data

    def get_chapter_id_for_url(self, url):
        return self.volume_id_regex.search(self.session_get(url).text).group(1)
