from manga_reader.server import Server
from PIL import Image


class TestServer(Server):
    id = 'test'
    has_login = False

    def __init__(self, settings):
        super().__init__(settings=settings)

        self.test_manga = [self.create_manga_data(id="1", name="Manga1"),
                           self.create_manga_data(id="2", name="Manga2"),
                           self.create_manga_data(id="3", name="Manga3")
                           ]

        self.test_pages = {
            "1": [self.create_page_data(url="") for k in range(3)],
            "2": [self.create_page_data(url="") for k in range(3)],
            "3": [self.create_page_data(url="") for k in range(3)],
            "4": [self.create_page_data(url="") for k in range(3)],
            "5": [self.create_page_data(url="") for k in range(3)]
        }

    def get_manga_list(self):
        return list(self.test_manga)

    def update_manga_data(self, manga_data):

        manga_id = manga_data["id"]
        if manga_id == "1":
            self.update_chapter_data(manga_data, id="1", title="Chapter1", number=1, date="2020-07-9"),
            self.update_chapter_data(manga_data, id="2", title="Chapter2", number=2, date="2020-07-10"),
            self.update_chapter_data(manga_data, id="3", title="Chapter3", number=3, date="2020-07-09")
        elif manga_id == "2":
            self.update_chapter_data(manga_data, id="4", title="Chapter1", number=1, date="1"),
        elif manga_id == "3":
            self.update_chapter_data(manga_data, id="5", title="ChapterN", number=1, date="today")
        else:
            assert False, "Invalid id"

    def get_manga_chapter_data(self, manga_data, chapter_data):
        return list(self.test_pages[chapter_data["id"]])

    def save_chapter_page(self, page_data, path):
        image = Image.new('RGB', (100, 100))
        image.save(path, "PNG")


class TestServer2(TestServer):
    id = 'test2'

    def get_manga_list(self):
        for i in range(10):
            self.session.get('http://httpbin.org/delay/10')
        return super().get_manga_list()
