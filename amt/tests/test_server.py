import os
import re
import subprocess

from PIL import Image
from requests.exceptions import HTTPError

from ..server import ANIME, MEDIA_TYPES, Server

TEST_BASE = "/tmp/amt/"


class TestServer(Server):
    id = "test_server_manga"
    extension = "png"
    _prefix = "Manga"
    error_to_inject = None
    time_to_error = 0
    error_count = 0
    domain = "test.com"
    hide = False
    inaccessible = False
    error_delay = 0

    def maybe_inject_error(self):
        if self.error_to_inject:
            if self.error_delay > 0:
                self.error_delay -= 1
                return
            self.error_count += 1
            try:
                raise self.error_to_inject
            finally:
                self.time_to_error -= 1
                if self.time_to_error == 0:
                    self.inject_error(None, 0)

    def inject_error(self, error=Exception("Dummy error"), count=1, delay=0):
        self.error_to_inject = error
        self.time_to_error = count
        self.error_delay = delay

    def was_error_thrown(self):
        return self.error_count

    def get_media_list(self):
        self.maybe_inject_error()
        media_type_name = [x for x in MEDIA_TYPES if MEDIA_TYPES[x] == self.media_type][0]
        return [self.create_media_data(id=1, name=f"{media_type_name}1"), self.create_media_data(id=2, name=f"{media_type_name}InProgress"), self.create_media_data(id=3, name="Untracked"), self.create_media_data(id=4, name="!@#$%^&* 's\",.?)(][:;_-=")]

    def update_media_data(self, media_data):
        self.maybe_inject_error()
        if self.hide:
            return
        media_id = media_data["id"]
        assert media_id in map(lambda x: x["id"], self.get_media_list())
        if media_id == 1:
            self.update_chapter_data(media_data, id=1, title="Chapter1", number=1, date="2020-07-08", premium=self.has_login),
            self.update_chapter_data(media_data, id=2, title="Chapter2", number=2, date="2020-07-09", premium=self.has_login),
            self.update_chapter_data(media_data, id=3, title="Chapter3", number=3, date="2020-07-10", premium=self.has_login)
        elif media_id == 2:
            self.update_chapter_data(media_data, id=4, title="Chapter1", number=1),
            self.update_chapter_data(media_data, id=5, title="Chapter1-1", number="1-1"),
            self.update_chapter_data(media_data, id=6, title="Chapter1.2", number="1.2"),
            self.update_chapter_data(media_data, id=7, title="Chapter10", number="10"),
            self.update_chapter_data(media_data, id=8, title="Chapter11", number="11"),
            self.update_chapter_data(media_data, id=9, title="Chapter10.5", number="10.5"),
            self.update_chapter_data(media_data, id=10, title="Chapter100", number="100"),
            self.update_chapter_data(media_data, id=11, title="Chapter1000", number="1000"),
            self.update_chapter_data(media_data, id=12, title="Chapter9999", number="9999", premium=self.has_login),
        elif media_id == 3:
            self.update_chapter_data(media_data, id=21, title="Chapter1", number=1, date="2020-07-08"),
            self.update_chapter_data(media_data, id=22, title="Chapter2", number=1.5, date="2020-07-08"),
            self.update_chapter_data(media_data, id=23, title="Chapter3", number=2, date="2020-07-08", premium=self.has_login),
            self.update_chapter_data(media_data, id=24, title="Chapter4", number=3, date="2020-07-08", premium=self.has_login),
        elif media_id == 4:
            self.update_chapter_data(media_data, id=25, title="Chapter1", number=2, date="1998-08-10"),
            self.update_chapter_data(media_data, id=26, title="ChapterSpecial", number=None, date="1998-08-10"),
            self.update_chapter_data(media_data, id=27, title="Chapter0.5", number=0.5, date="1998-08-10", special=True),
            self.update_chapter_data(media_data, id=28, title="Chapter4", number=4, date="1998-08-10", inaccessible=self.inaccessible),

    def get_media_chapter_data(self, media_data, chapter_data):
        self.maybe_inject_error()
        return [self.create_page_data(url=f"https://some_url.com/{chapter_data['id']}.{self.extension}") for k in range(3)]

    def save_chapter_page(self, page_data, path):
        self.maybe_inject_error()
        assert not os.path.exists(path)
        image = Image.new("RGB", (100, 100))
        image.save(path, self.extension)


class TestServerLogin(TestServer):
    id = "test_server_login"
    counter = 0
    premium_account = True
    error_login = False

    def needs_authentication(self):
        if self.error_login:
            raise HTTPError()
        return super().needs_authentication()

    def login(self, username, password):
        self.counter += 1
        if self.error_login:
            raise HTTPError()
        self.is_premium = self.premium_account
        return True

    def reset(self):
        self.counter = 0
        self._is_logged_in = False


class TestUnofficialServer(TestServer):
    id = "test_unofficial_server_manga"
    official = False


class TestAnimeServer(TestServer):
    id = "test_server_anime"
    media_type = ANIME
    _prefix = "Anime"
    extension = "ts"
    TEST_VIDEO_PATH = ""
    stream_url = "https://www.test/url/4"
    stream_url_regex = re.compile(r".*/([0-9])")
    is_protected = True

    def get_chapter_id_for_url(self, url):
        assert self.can_stream_url(url)
        assert url == self.stream_url
        return self.stream_url_regex.match(url).group(1)

    def get_media_data_from_url(self, url):
        assert self.can_stream_url(url)
        media_data = self.get_media_list()[1]
        self.update_media_data(media_data)
        return media_data

    def get_stream_urls(self, media_data=None, chapter_data=None):
        assert isinstance(media_data, dict) if media_data else True
        assert isinstance(chapter_data, dict) if chapter_data else True
        return [f"https://{self.domain}/url.m3u8?key=1&false"]

    def save_chapter_page(self, page_data, path):
        self.maybe_inject_error()
        assert not os.path.exists(path)
        if not TestAnimeServer.TEST_VIDEO_PATH:
            os.makedirs(TEST_BASE, exist_ok=True)
            TestAnimeServer.TEST_VIDEO_PATH = TEST_BASE + "test_video.mp4"
            subprocess.check_call(["ffmpeg", "-y", "-loglevel", "quiet", "-f", "lavfi", "-i", "testsrc=duration=1:size=10x10:rate=30", TestAnimeServer.TEST_VIDEO_PATH])
        os.link(TestAnimeServer.TEST_VIDEO_PATH, path)
