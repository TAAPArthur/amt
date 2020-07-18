from PIL import Image
import logging
import os
import shutil
import time
import unittest
import sys

from ..manga_reader import MangaReader, SERVERS
from ..settings import Settings
from .test_server import TestServer, TestServer2

TEST_HOME = "/tmp/manga_reader/test_home"


logging.basicConfig(format='[%(filename)s:%(lineno)s]%(levelname)s:%(message)s', level=logging.INFO)
logger = logging.getLogger()
stream_handler = logging.StreamHandler(sys.stdout)
logger.addHandler(stream_handler)


class TestMangaReader(MangaReader):
    def __init__(self, class_list):
        # Save cache in local directory
        os.putenv('XDG_CACHE_HOME', ".")
        stream_handler.stream = sys.stdout
        settings = Settings(home=TEST_HOME)
        settings.init()
        settings.cache = True
        settings.free_only = True
        settings.password_manager_enabled = False
        if class_list:
            super().__init__(class_list, settings)
        else:
            super().__init__(settings=settings)
        assert len(self.get_servers())
        assert all(self.get_servers())


class BaseUnitTestClass(unittest.TestCase):
    def setUp(self):
        self.manga_reader = TestMangaReader([TestServer, TestServer2, ] + SERVERS)
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


class ServerTest(BaseUnitTestClass):
    def test_get_manga_list(self):
        for server in self.manga_reader.get_servers():
            with self.subTest(server=server.id, method="get_manga_list"):
                manga_list = server.get_manga_list()
                assert isinstance(manga_list, list)
                assert all([isinstance(x, dict) for x in manga_list])
            with self.subTest(server=server.id, method="search"):
                search_manga_list = server.search("a")
                assert isinstance(search_manga_list, list)
                assert all([isinstance(x, dict) for x in search_manga_list])

            for i in (0, -1):
                manga_data = manga_list[i]
                with self.subTest(server=server.id, method="update_manga_data", i=i):
                    return_val = server.update_manga_data(manga_data)
                    assert not return_val
                    assert isinstance(manga_data["chapters"], dict)

    def test_caching(self):
        start = time.time()
        for i in range(10):
            list(self.manga_reader.get_servers())[0].session.get('http://httpbin.org/delay/1')
        assert time.time() - start < 5

    def test_login_fail(self):
        for server in self.manga_reader.get_servers():
            if not server.has_login:
                continue

            with self.subTest(server=server.id, method="login"):
                assert not server.login("A", "B")

            server.settings.password_load_cmd = r"echo -e A\\tB"
            with self.subTest(server=server.id, method="relogin"):
                assert not server.relogin()


class MangaReaderTest(BaseUnitTestClass):

    def test_number_servers(self):
        assert len(self.manga_reader.get_servers()) > 2

    def test_save_load(self):
        for server in self.manga_reader.get_servers():
            with self.subTest(server=server.id):
                manga_list = server.get_manga_list()
                self.manga_reader.add_manga(manga_list[0])
                old_state = dict(self.manga_reader.state)
                self.manga_reader.save_state()
                assert old_state == dict(self.manga_reader.state)
                self.manga_reader.state.clear()
                self.manga_reader.load_state()
                assert old_state == self.manga_reader.state
                self.manga_reader.state.clear()

    def test_mark_chapters_until_n_as_read(self):

        for server in self.manga_reader.get_servers():
            with self.subTest(server=server.id):
                self.manga_reader.state.clear()
                manga_list = server.get_manga_list()
                manga_data = None
                for manga_data in manga_list:
                    self.manga_reader.add_manga(manga_data)
                    if len(manga_data["chapters"]) > 2:
                        break
                    self.manga_reader.remove_manga(manga_data)
                assert len(manga_data["chapters"]) > 2
                last_chapter_num = max(manga_data["chapters"].values(), key=lambda x: x["number"])["number"]
                last_chapter_num_read = last_chapter_num - 1
                assert last_chapter_num > 1
                self.manga_reader.mark_chapters_until_n_as_read(manga_data, last_chapter_num_read)

                assert all(map(lambda x: x["read"], filter(lambda x: last_chapter_num_read >= x["number"], manga_data["chapters"].values())))

                def fake_download_chapter(manga_data, chapter_data):
                    assert chapter_data["number"] > last_chapter_num_read

                server.download_chapter = fake_download_chapter
                self.manga_reader.download_unread_chapters()

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
                chapter_data = self.manga_reader.update_manga(manga_data, download=True, limit=1, page_limit=3)[0]
                dir_path = self.manga_reader.settings.get_chapter_dir(manga_data, chapter_data)

                dirpath, dirnames, filenames = list(os.walk(dir_path))[0]
                assert filenames
                for file_name in filenames:
                    with open(os.path.join(dirpath, file_name), "rb") as img_file:
                        Image.open(img_file)

                # error if we try to save a page we have already downloaded
                server.save_chapter_page = None
                self.manga_reader.update_manga(manga_data, download=True, limit=1, page_limit=3)
