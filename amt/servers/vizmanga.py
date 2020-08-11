from PIL import Image
from bs4 import BeautifulSoup
import re
import logging

from ..server import Server

# Improved from https://github.com/media-py/media-py


class VizManga(Server):
    id = "vizmedia"
    lang = "en"
    locale = "enUS"

    has_login = True

    base_url = "http://www.viz.com"
    login_url = base_url + "/media/try_media_login"
    refresh_login_url = base_url + "/account/refresh_login_links"
    login_url = base_url + "/account/try_login"
    api_series_url = base_url + "/shonenjump"
    api_chapters_url = base_url + "/shonenjump/chapters/{}"
    api_chapter_data_url = base_url + "/media/get_media_url?device_id=3&media_id={}&page={}"
    api_chapter_url = base_url + "/shonenjump/{}-chapter-{}/chapter/{}"

    chapter_regex = re.compile(r"/shonenjump/(.*)-chapter-([\d\-]*)/chapter/(\d*)")
    page_regex = re.compile(r"var pages\s*=\s*(\d*);")

    def get_token(self):
        auth_token = self.session_get(self.refresh_login_url)
        token = re.search(r'AUTH_TOKEN\s*=\s*"(.+?)"', auth_token.text)
        return token.group(1)

    def needs_authentication(self):
        r = self.session_get(self.refresh_login_url)
        soup = BeautifulSoup(r.content, "lxml")
        account = soup.find("div", id="o_account-links-content")
        return not account or account["logged_in"] == "false"

    def login(self, username, password):
        token = self.get_token()

        r = self.session_post(
            self.login_url,
            data={
                "login": username,
                "pass": password,
                "rem_user": 1,
                "authenticity_token": token,
            })
        return r.status_code == 200

    def get_media_list(self):
        r = self.session_get(self.api_series_url)

        soup = BeautifulSoup(r.content, "lxml")
        divs = soup.findAll("a", {"class": "disp-bl pad-b-rg pos-r bg-off-black color-white hover-bg-red"})
        result = []
        for div in divs:
            id = div["href"].split("/")[-1]
            name = div.find("div", {"class", "pad-x-rg pad-t-rg pad-b-sm type-sm type-rg--sm type-md--lg type-center line-solid"}).getText().strip()
            cover_url = div.find("img")["data-original"]

            result.append(self.create_media_data(id=id, name=name, cover=cover_url))

        return result

    def update_media_data(self, media_data):
        r = self.session_get(self.api_chapters_url.format(media_data["id"]))
        soup = BeautifulSoup(r.content, "lxml")

        authors = []
        synopsis = ""
        media_info = soup.find("section", {"id": "series-intro"})
        if media_info:
            author_element = media_info.find("span", {"class": "disp-bl--bm mar-b-md"})
            authors = author_element.getText().split(",") if author_element else ""
            synposis_element = media_info.find("h4")
            synopsis = synposis_element.getText().strip() if synposis_element else ""

        ongoing = soup.find("div", {"class": "section_future_chapter"})
        status = "ongoing" if ongoing else "complete"

        media_data["info"] = dict(
            authors=authors,
            scanlators=[],
            genres=[],
            status=status,
            synopsis=synopsis,
        )

        # Chapters
        chapters = soup.findAll("a", {"class": "o_chapter-container"})
        if ongoing:
            chapters.reverse()
        slugs = set()
        for chapter in chapters:
            raw_url_maybe = chapter["data-target-url"]
            match = self.chapter_regex.search(raw_url_maybe)
            series_name = match.group(1)
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

            # There seems to be a title field in the metadata... it doesn"t seem useful nor unique
            # eg "My Hero Academia: Vigilantes Chapter 1.0"
            # so we"ll just use the chapter number as the title
            title = chapter_number

            self.update_chapter_data(media_data, id=chapter_id, number=chapter_number, premium=premium, title=title, date=chapter_date)

    def get_media_chapter_data(self, media_data, chapter_data):
        chapter_url = self.api_chapter_url.format(media_data["id"], str(chapter_data["number"]).replace(".", "-"), chapter_data["id"])
        match = self.page_regex.search(self.session_get(chapter_url).text)
        num_pages = int(match.group(1)) + 1

        pages = []
        for i in range(num_pages):
            pages.append(self.create_page_data(url=self.api_chapter_data_url.format(chapter_data["id"], i)))
        return pages

    def save_chapter_page(self, page_data, path):
        r = self.session_get(page_data["url"], headers={"Referer": "https://www.viz.com"})
        if r.status_code != 200:
            logging.warning("Could not load page_data['url']; Response code %d", r.status_code)
            return
        real_img_url = r.text.strip()

        r = self.session_get(real_img_url, stream=True)
        if r.status_code != 200:
            return None

        orig = Image.open(r.raw)  # type: Image.Image
        solution = VizManga.solve_image(orig)
        solution.save(path)

    @staticmethod
    def solve_image(orig: Image) -> Image.Image:
        new_size = (orig.size[0] - 90, orig.size[1] - 140)
        ref = Image.new(orig.mode, new_size)  # type: Image.Image
        ref.paste(orig)

        _key = 42016
        exif = orig.getexif()
        key = [int(i, 16) for i in exif[_key].split(':')]
        width, height = exif[256], exif[257]

        small_width = int(width / 10)
        small_height = int(height / 15)

        VizManga.paste(ref, orig, (
            0, small_height + 10,
            small_width, height - 2 * small_height,
        ), (
            0, small_height,
            small_width, height - 2 * small_height,
        ))

        VizManga.paste(ref, orig, (
            0, 14 * (small_height + 10),
            width, orig.height - 14 * (small_height + 10),
        ), (
            0, 14 * small_height,
            width, orig.height - 14 * (small_height + 10),
        ))

        VizManga.paste(ref, orig, (
            9 * (small_width + 10), small_height + 10,
            small_width + (width - 10 * small_width), height - 2 * small_height,
        ), (
            9 * small_width, small_height,
            small_width + (width - 10 * small_width), height - 2 * small_height,
        ))

        for i, j in enumerate(key):
            VizManga.paste(ref, orig, (
                (i % 8 + 1) * (small_width + 10), (int(i / 8) + 1) * (small_height + 10),
                small_width, small_height,
            ), (
                (j % 8 + 1) * small_width, (int(j / 8) + 1) * small_height,
                small_width, small_height,
            ))

        return ref

    @ staticmethod
    def paste(ref: Image.Image, orig: Image.Image, orig_box, ref_box):
        ref.paste(orig.crop((
            int(orig_box[0]), int(orig_box[1]),
            int(orig_box[0] + orig_box[2]), int(orig_box[1] + orig_box[3]),
        )), (
            int(ref_box[0]), int(ref_box[1]),
            int(ref_box[0] + ref_box[2]), int(ref_box[1] + ref_box[3]),
        ))
