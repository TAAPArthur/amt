import os
import re
import subprocess

from PIL import Image

from ..server import ANIME, Server

TEST_BASE = "/tmp/amt/"


class TestServer(Server):
    id = "test_server_manga"
    has_gaps = True
    extension = "jpeg"
    _prefix = "Manga"
    _throw_error = False
    _error_thrown = False
    domain = "test.com"

    def maybe_inject_error(self):
        if self._throw_error:
            self._error_thrown = True
            raise Exception("Injected Error from {}".format(self.id))

    def inject_error(self):
        self._throw_error = True

    def was_error_thrown(self):
        return self._error_thrown

    def get_media_list(self):
        self.maybe_inject_error()
        return [self.create_media_data(id=1, name=self._prefix + "1"), self.create_media_data(id=2, name=self._prefix + "InProgress"), self.create_media_data(id=3, name="Untracked"), self.create_media_data(id=4, name="!@#$%^&* 's\",.?)(][:;_-=")]

    def update_media_data(self, media_data):
        self.maybe_inject_error()
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
            self.update_chapter_data(media_data, id=12, title="Chapter9999", number="9999"),
        elif media_id == 3:
            self.update_chapter_data(media_data, id=21, title="Chapter1", number=1, date="2020-07-08"),
            self.update_chapter_data(media_data, id=22, title="Chapter2", number=1.5, date="2020-07-08"),
            self.update_chapter_data(media_data, id=23, title="Chapter3", number=2, date="2020-07-08"),
            self.update_chapter_data(media_data, id=24, title="Chapter4", number=3, date="2020-07-08"),
        elif media_id == 4:
            self.update_chapter_data(media_data, id=25, title="Chapter1", number=2, date="1998-08-10"),
            self.update_chapter_data(media_data, id=26, title="Chapter1", number=1, date="1998-08-10"),
            self.update_chapter_data(media_data, id=27, title="Chapter1", number=0.5, date="1998-08-10", special=True),

    def get_media_chapter_data(self, media_data, chapter_data):
        self.maybe_inject_error()
        return [self.create_page_data(url="some_url") for k in range(int(media_data["id"]) + 3)]

    def save_chapter_page(self, page_data, path):
        self.maybe_inject_error()
        assert not os.path.exists(path)
        image = Image.new("RGB", (100, 100))
        image.save(path, self.extension)


class TestServerLogin(TestServer):
    id = "test_server_login"
    counter = 0
    fail_login = False
    has_login = True
    logged_in = False

    def login(self, username, password):
        self.counter += 1
        self.is_premium = not self.fail_login
        self.logged_in = not self.fail_login
        return self.logged_in

    def relogin(self):
        return self.login(None, None)

    def needs_authentication(self):
        return not self.logged_in

    def reset(self):
        self.counter = 0
        self.logged_in = False


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

    def get_stream_urls(self, media_data=None, chapter_data=None, url=None):
        assert isinstance(media_data, dict) if media_data else True
        assert isinstance(chapter_data, dict) if chapter_data else True
        assert isinstance(url, str) if url else True
        return [f"https://{self.domain}/url.m3u8?key=1&false"]

    def save_chapter_page(self, page_data, path):
        self.maybe_inject_error()
        assert not os.path.exists(path)
        if not TestAnimeServer.TEST_VIDEO_PATH:
            os.makedirs(TEST_BASE, exist_ok=True)
            TestAnimeServer.TEST_VIDEO_PATH = TEST_BASE + "test_video.mp4"
            subprocess.check_call(["ffmpeg", "-y", "-loglevel", "quiet", "-f", "lavfi", "-i", "testsrc=duration=1:size=10x10:rate=30", TestAnimeServer.TEST_VIDEO_PATH])
        os.link(TestAnimeServer.TEST_VIDEO_PATH, path)

    def session_get_protected(self, url, **kwargs):
        return None
