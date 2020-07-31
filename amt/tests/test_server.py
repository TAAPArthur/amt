from ..server import Server
from PIL import Image
import os


class TestServer(Server):
    id = 'test'
    has_gaps = True

    def get_manga_list(self):
        return [self.create_manga_data(id=1, name="Manga1"), self.create_manga_data(id=2, name="Manga2")]

    def update_manga_data(self, manga_data):
        manga_id = manga_data["id"]
        assert manga_id in map(lambda x: x["id"], self.get_manga_list())
        if manga_id == 1:
            self.update_chapter_data(manga_data, id=1, title="Chapter1", number=1, date="2020-07-08"),
            self.update_chapter_data(manga_data, id=2, title="Chapter2", number=2, date="2020-07-09"),
            self.update_chapter_data(manga_data, id=3, title="Chapter3", number=3, date="2020-07-10")
        elif manga_id == 2:
            self.update_chapter_data(manga_data, id=4, title="Chapter1", number=1),
            self.update_chapter_data(manga_data, id=5, title="Chapter1-1", number="1-1"),
            self.update_chapter_data(manga_data, id=6, title="Chapter1.2", number="1.2"),
            self.update_chapter_data(manga_data, id=7, title="Chapter10", number="10"),
            self.update_chapter_data(manga_data, id=8, title="Chapter11", number="11"),
            self.update_chapter_data(manga_data, id=9, title="Chapter10.5", number="10.5"),
            self.update_chapter_data(manga_data, id=10, title="Chapter100", number="100"),
            self.update_chapter_data(manga_data, id=11, title="Chapter1000", number="1000"),
            self.update_chapter_data(manga_data, id=12, title="Chapter9999", number="9999"),

    def get_manga_chapter_data(self, manga_data, chapter_data):
        return [self.create_page_data(url="") for k in range(3)]

    def save_chapter_page(self, page_data, path):
        assert not os.path.exists(path)
        image = Image.new('RGB', (100, 100))
        image.save(path, "PNG")
