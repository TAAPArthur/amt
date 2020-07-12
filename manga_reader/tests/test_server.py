from manga_reader.server import Server
from manga_reader.manga_data import create_manga_data, ChapterData, PageData
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
            "1": [ChapterData(id="1", title="Chapter1", date="2020-07-11")],
            "2": [ChapterData(id="2", title="Chapter1", date="1")],
            "3": [ChapterData(id="3", title="ChapterN", date="today")]
        }

        self.test_pages = {
            "1": [PageData(url="") for k in range(3)],
            "2": [PageData(url="") for k in range(3)],
            "3": [PageData(url="") for k in range(3)]
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
