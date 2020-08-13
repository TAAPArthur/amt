import os

from PIL import Image

from ..server import ANIME, Server


class TestServer(Server):
    id = 'test_server_manga'
    has_gaps = True
    _prefix = "Manga"

    def get_media_list(self):
        return [self.create_media_data(id=1, name=self._prefix + "1"), self.create_media_data(id=2, name=self._prefix + "2"), self.create_media_data(id=3, name="Untracked")]

    def update_media_data(self, media_data):
        media_id = media_data["id"]
        assert media_id in map(lambda x: x["id"], self.get_media_list())
        if media_id == 1:
            self.update_chapter_data(media_data, id=1, title="Chapter1", number=1, date="2020-07-08"),
            self.update_chapter_data(media_data, id=2, title="Chapter2", number=2, date="2020-07-09"),
            self.update_chapter_data(media_data, id=3, title="Chapter3", number=3, date="2020-07-10")
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

    def get_media_chapter_data(self, media_data, chapter_data):
        return [self.create_page_data(url="") for k in range(3)]

    def save_chapter_page(self, page_data, path):
        assert not os.path.exists(path)
        image = Image.new('RGB', (100, 100))
        image.save(path, "PNG")


class TestAnimeServer(TestServer):
    id = 'test_server_anime'
    media_type = ANIME
    _prefix = "Anime"

    def get_stream_url(self, media_data, chapter_data):
        return "url.m3u8"
