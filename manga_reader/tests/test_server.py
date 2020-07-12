from manga_reader.server import Server
from manga_reader.manga_data import create_manga_data, create_chapter_data, create_page_data
from PIL import Image


class TestServer(Server):
    id = 'test'
    has_login = False

    def __init__(self, settings):
        super().__init__(settings=settings)

        self.test_manga = [create_manga_data(server_id=self.id, id="1", name="Manga1"),
                           create_manga_data(server_id=self.id, id="2", name="Manga2"),
                           create_manga_data(server_id=self.id, id="3", name="Manga3")
                           ]
        self.test_chapters = {
            "1": [
                create_chapter_data(id="1", title="Chapter1", number=1, date="2020-07-9"),
                create_chapter_data(id="2", title="Chapter2", number=2, date="2020-07-10"),
                create_chapter_data(id="3", title="Chapter3", number=3, date="2020-07-09")
            ],
            "2": [create_chapter_data(id="4", title="Chapter1", number=1, date="1")],
            "3": [create_chapter_data(id="5", title="ChapterN", number=1, date="today")]
        }

        self.test_pages = {
            "1": [create_page_data(url="") for k in range(3)],
            "2": [create_page_data(url="") for k in range(3)],
            "3": [create_page_data(url="") for k in range(3)],
            "4": [create_page_data(url="") for k in range(3)],
            "5": [create_page_data(url="") for k in range(3)]
        }

    def get_manga_list(self):
        return list(self.test_manga)

    def update_manga_data(self, data):
        data["chapters"] = list(self.test_chapters[data["id"]])

    def get_manga_chapter_data(self, manga_data, chapter_data):
        return list(self.test_pages[chapter_data["id"]])

    def save_chapter_page(self, page_data, path):
        image = Image.new('RGB', (100, 100))
        image.save(path, "PNG")


class TestServer2(TestServer):
    id = 'test2'
