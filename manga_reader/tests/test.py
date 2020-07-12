import unittest
import shutil
import os
from PIL import Image

from manga_reader.manga_reader import MangaReader
from manga_reader.settings import Settings
from manga_reader.tests.test_server import TestServer, TestServer2

TEST_HOME = "/tmp/manga_reader/test_home"


class TestMangaReader(MangaReader):
    def __init__(self, class_list):
        settings = Settings(home=TEST_HOME)
        settings.init()
        if class_list:
            super().__init__(class_list, settings)
        else:
            super().__init__(settings=settings)


class BaseUnitTestClass(unittest.TestCase):
    def setUp(self):
        self.manga_reader = TestMangaReader([TestServer, TestServer2])
        assert not self.manga_reader.state

    def tearDown(self):
        shutil.rmtree(TEST_HOME, ignore_errors=True)


class SettingsTest(BaseUnitTestClass):
    def test_settings_save_load(self):
        settings = Settings(home=TEST_HOME)
        settings.manga_viewer_cmd = "dummy_cmd"
        settings.save()

        settings = Settings(home=TEST_HOME)
        assert settings.manga_viewer_cmd == "dummy_cmd"


class ServerWorkflowsTest(BaseUnitTestClass):

    def test_manga_reader_add_remove_manga(self):
        for server in self.manga_reader.get_servers():
            manga_list = server.get_manga_list()
            assert manga_list
            selected_manga = manga_list[0]
            self.manga_reader.add_manga(selected_manga)
            my_manga_list = list(self.manga_reader.get_manga_in_library())
            assert 1 == len(my_manga_list)
            assert my_manga_list[0]["id"] == selected_manga["id"]
            self.manga_reader.remove_manga(manga_data=selected_manga)
            assert 0 == len(self.manga_reader.get_manga_in_library())

    def test_search_manga(self):
        for server in self.manga_reader.get_servers():
            manga_data = server.get_manga_list()[0]
            name = manga_data["name"]
            assert manga_data == list(server.search(name))[0]
            assert server.search(name[:3])

    def test_search_for_manga(self):
        servers = set()
        for term in ["a", "e", "i", "o", "u"]:
            servers |= {x["server_id"] for x in self.manga_reader.search_for_manga(term)}
        assert len(self.manga_reader.get_servers()) == len(servers)


class MangaReaderTest(BaseUnitTestClass):

    def test_save_load(self):
        for server in self.manga_reader.get_servers():
            manga_list = server.get_manga_list()
            self.manga_reader.add_manga(manga_list[0])

        old_state = dict(self.manga_reader.state)
        self.manga_reader.save_state()
        self.manga_reader.state.clear()
        self.manga_reader.load_state()
        assert old_state == self.manga_reader.state

    def test_update_no_manga(self):
        assert not self.manga_reader.update()

    def test_update(self):
        for server in self.manga_reader.get_servers():
            with self.subTest(server=server.id):
                manga_list = server.get_manga_list()
                manga_data = manga_list[0]
                assert not self.manga_reader.update()
                new_chapters = self.manga_reader.add_manga(manga_data)
                assert new_chapters
                assert not self.manga_reader.update()

                manga_data["chapters"].clear()
                new_chapters2 = self.manga_reader.update_manga(manga_data)
                assert new_chapters == new_chapters2

    def test_update_download(self):
        for server in self.manga_reader.get_servers():
            with self.subTest(server=server.id):
                manga_list = server.get_manga_list()
                manga_data = manga_list[0]
                self.manga_reader.add_manga(manga_data, no_update=True)
                chapter_data = self.manga_reader.update_manga(manga_data, download=True, limit=1)[0]
                dir_path = self.manga_reader.settings.get_chapter_dir(manga_data, chapter_data)

                dirpath, dirnames, filenames = list(os.walk(dir_path))[0]
                assert filenames
                for file_name in filenames:
                    with open(os.path.join(dirpath, file_name), "rb") as img_file:
                        Image.open(img_file)
