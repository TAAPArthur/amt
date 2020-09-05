import os

from PIL import Image

from ..server import ANIME, Server


class TestServer(Server):
    id = 'test_server_manga'
    has_gaps = True
    _prefix = "Manga"
    _throw_error = False
    _error_thrown = False

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
            self.update_chapter_data(media_data, id=0, title="Chapter0", number=0, date="2020-08-08", premium=self.has_login),
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
            self.update_chapter_data(media_data, id=25, title="Chapter1", number=1, date="1998-08-10"),
            self.update_chapter_data(media_data, id=26, title="Chapter1", number=0, date="1998-08-10"),

    def get_media_chapter_data(self, media_data, chapter_data):
        self.maybe_inject_error()
        return [self.create_page_data(url="") for k in range(3)]

    def save_chapter_page(self, page_data, path):
        self.maybe_inject_error()
        assert not os.path.exists(path)
        image = Image.new('RGB', (100, 100))
        image.save(path, self.extension)


class TestServerLogin(TestServer):
    id = 'test_server_login'
    counter = 0
    fail_login = False
    has_login = True

    def login(self, username, password):
        TestServerLogin.counter += 1
        return not TestServerLogin.fail_login


class TestAnimeServer(TestServer):
    id = 'test_server_anime'
    media_type = ANIME
    _prefix = "Anime"
    stream_url = "test_url"

    def can_stream_url(self, url):
        return url == TestAnimeServer.stream_url

    def is_url_for_known_media(self, url, known_media):
        print(self.can_stream_url(url), self.get_media_list()[1]["id"] in known_media, known_media)

        media_id = self.get_media_list()[1]["id"]
        if self.can_stream_url(url) and media_id in known_media:
            return known_media[media_id], list(known_media[media_id]["chapters"].values())[0]

    def get_media_data_from_url(self, url):
        assert self.can_stream_url(url)
        return self.get_media_list()[1]

    def get_stream_url(self, media_id=None, chapter_id=None, url=None):
        return "url.m3u8"
