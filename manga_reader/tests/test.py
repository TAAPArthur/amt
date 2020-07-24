from PIL import Image
import logging
import os
import shutil
import time
import unittest
from unittest.mock import patch
import sys

from ..manga_reader import MangaReader, SERVERS
from ..app import Application
from ..settings import Settings
from .test_server import TestServer, TestServer2
from ..main import parse_args

TEST_HOME = "/tmp/manga_reader/test_home/"


logging.basicConfig(format='[%(filename)s:%(lineno)s]%(levelname)s:%(message)s', level=logging.INFO)
logger = logging.getLogger()
stream_handler = logging.StreamHandler(sys.stdout)
logger.addHandler(stream_handler)


class TestApplication(Application):
    def __init__(self, class_list):
        # Save cache in local directory
        os.putenv('XDG_CACHE_HOME', ".")
        stream_handler.stream = sys.stdout
        settings = Settings(home=TEST_HOME)
        settings.init()
        settings.expire_after = 7 * 24 * 60 * 60
        settings.shell = True
        settings.cache = True
        settings.free_only = True
        settings.password_manager_enabled = False
        super().__init__(class_list, settings)
        assert len(self.get_servers())
        assert all(self.get_servers())


class BaseUnitTestClass(unittest.TestCase):
    def setUp(self):
        self.app = TestApplication([TestServer, TestServer2, ] + SERVERS)
        self.manga_reader = self.app
        self.settings = self.manga_reader.settings
        assert not self.manga_reader.get_manga_in_library()

    def tearDown(self):
        shutil.rmtree(TEST_HOME, ignore_errors=True)

    def add_arbitrary_manga(self):
        server = self.manga_reader.get_server(TestServer.id)
        for manga_data in server.get_manga_list():
            self.manga_reader.add_manga(manga_data)


class SettingsTest(BaseUnitTestClass):
    def test_settings_save_load(self):
        settings = Settings(home=TEST_HOME)
        settings.manga_viewer_cmd = "dummy_cmd"
        settings.save()

        settings = Settings(home=TEST_HOME)
        assert settings.manga_viewer_cmd == "dummy_cmd"

    def test_credentials(self):
        settings = Settings(home=TEST_HOME)
        settings.password_manager_enabled = True
        settings.password_load_cmd = "cat {}{}".format(TEST_HOME, "{}")
        settings.password_save_cmd = r"cat - >> {}{}".format(TEST_HOME, "{}")
        server_id = "test"
        assert not settings.get_credentials(server_id)
        username, password = "user", "pass"
        settings.store_credentials(server_id, username, password)
        assert (username, password) == settings.get_credentials(server_id)
        tracker_id = "test-tracker"
        assert not settings.get_credentials(tracker_id)
        assert not settings.get_secret(tracker_id)
        secret = "MySecret"
        settings.store_secret(tracker_id, secret)
        assert secret == settings.get_secret(tracker_id)

    def test_bundle(self):
        settings = Settings(home=TEST_HOME)
        settings.bundle_format = "pdf"
        settings.bundle_cmds[settings.bundle_format] = "echo {} {}"
        settings.viewers[settings.bundle_format] = "echo {}"
        name = settings.bundle("")
        assert name.endswith("." + settings.bundle_format)
        assert settings.view(name)

        settings.viewers[settings.bundle_format] = "exit 1"
        assert not settings.view(name)

    def test_get_chapter_dir(self):
        settings = Settings(home=TEST_HOME)
        server = TestServer(None, settings)
        manga_data = server.create_manga_data("id", "Manga Name")
        server.update_chapter_data(manga_data, "chapter_id", title="Degenerate Chapter Title ~//\\\\!@#$%^&*()", number="1-2")
        dir = settings.get_chapter_dir(manga_data, manga_data["chapters"]["chapter_id"])
        # should yield the same result everytime
        assert dir == settings.get_chapter_dir(manga_data, manga_data["chapters"]["chapter_id"])

        settings.bundle_cmds[settings.bundle_format] = "ls {}; echo {}"

        name = settings.bundle(dir)


class TrackerTest(BaseUnitTestClass):
    def test_get_list(self):

        tracker = self.manga_reader.get_primary_tracker()

        data = tracker.get_tracker_list(id=1)
        assert data
        assert isinstance(data, list)
        assert isinstance(data[0], dict)

    @patch('builtins.input', return_value='value')
    def test_auth(self, input):
        tracker = self.manga_reader.get_primary_tracker()
        assert "value" == tracker.auth()


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

            with self.subTest(server=server.id, method="search"):
                manga_data = manga_list[0]
                chapter_data = list(manga_data["chapters"].values())[0]
                if not chapter_data["premium"]:
                    assert server.download_chapter(manga_data, chapter_data, page_limit=1)
                assert not server.download_chapter(manga_data, chapter_data, page_limit=1)

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

            server.settings.password_manager_enabled = False
            with self.subTest(server=server.id, method="relogin"):
                assert not server.relogin()

            server.settings.password_manager_enabled = True
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
                self.manga_reader.manga.clear()
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

        self.manga_reader.settings.free_only = False
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
            if not server.has_free_chapters:
                continue
            with self.subTest(server=server.id):
                manga_list = server.get_manga_list()
                manga_data = manga_list[0]
                self.manga_reader.add_manga(manga_data, no_update=True)
                chapter_data = self.manga_reader.update_manga(manga_data, download=True, limit=1, page_limit=3)[0]
                min_chapter = min(manga_data["chapters"].values(), key=lambda x: x["number"])
                assert min_chapter == chapter_data
                dir_path = self.manga_reader.settings.get_chapter_dir(manga_data, chapter_data)

                dirpath, dirnames, filenames = list(os.walk(dir_path))[0]
                assert filenames
                for file_name in filenames:
                    with open(os.path.join(dirpath, file_name), "rb") as img_file:
                        Image.open(img_file)

                # error if we try to save a page we have already downloaded
                server.save_chapter_page = None
                assert not server.download_chapter(manga_data, chapter_data, page_limit=3)

    def _prepare_for_bundle(self):
        server = self.manga_reader.get_server(TestServer.id)
        manga_list = server.get_manga_list()
        num_chapters = 0
        for manga_data in manga_list:
            self.manga_reader.add_manga(manga_data)
            num_chapters += len(manga_data["chapters"])

        self.assertEqual(num_chapters, self.manga_reader.download_unread_chapters())

        self.settings.bundle_cmds[self.settings.bundle_format] = "echo {{}} > {}/{{}}".format(TEST_HOME)
        self.settings.viewers[self.settings.bundle_format] = "echo {}"

    def test_bundle(self):
        self._prepare_for_bundle()
        name = self.manga_reader.bundle_unread_chapters()
        assert self.manga_reader.read_bundle(name)
        assert all([x["read"] for manga_data in self.manga_reader.get_manga_in_library() for x in manga_data["chapters"].values()])

    def test_bundle_shuffle(self):
        self._prepare_for_bundle()
        names = set()
        for i in range(10):
            names.add(self.manga_reader.bundle_unread_chapters(shuffle=True))
        assert all(names)
        assert len(names) > 1

    def test_bundle_no_unreads(self):
        assert not self.manga_reader.bundle_unread_chapters()

    def test_bundle_fail(self):
        self._prepare_for_bundle()
        self.settings.viewers[self.settings.bundle_format] = "exit 1; echo {};"
        assert not self.manga_reader.read_bundle("none.{}".format(self.settings.bundle_format))
        assert not any([x["read"] for manga_data in self.manga_reader.get_manga_in_library() for x in manga_data["chapters"].values()])


class ApplicationTest(BaseUnitTestClass):

    def test_list(self):
        self.add_arbitrary_manga()
        self.app.list()

    def test_list_chapters(self):
        self.add_arbitrary_manga()
        for id in self.manga_reader.get_manga_ids_in_library():
            self.app.list_chapters(id)

    @patch('builtins.input', return_value='0')
    def test_search_add(self, input):
        manga_data = self.app.search_add("manga")
        assert(manga_data)
        assert manga_data in self.manga_reader.get_manga_in_library()

    @patch('builtins.input', return_value='a')
    def test_search_add_nan(self, input):
        assert not self.app.search_add("manga")

    @patch('builtins.input', return_value='1000')
    def test_search_add_out_or_range(self, input):
        assert not self.app.search_add("manga")

    @patch('builtins.input', return_value='0')
    def test_load_from_tracker(self, input):
        for j in range(3):
            if j == 2:
                self.settings.trackers.clear()
            count, new_count = 0, 0
            for i in range(1, 3):
                c, n = self.app.load_from_tracker(user_id=i)
                assert c >= n
                count += c
                new_count += n
            if j == 1:
                self.assertEqual(0, new_count)
            else:
                self.assertEqual(new_count, len(self.manga_reader.get_manga_in_library()))


class ArgsTest(BaseUnitTestClass):
    @patch('builtins.input', return_value='0')
    def test_arg(self, input):
        parse_args(app=self.manga_reader, args=["auth"])

    def test_get_settings(self):
        parse_args(app=self.manga_reader, args=["get", "password_manager_enabled"])

    def test_set_settings_bool(self):
        parse_args(app=self.manga_reader, args=["set", "password_manager_enabled", "false"])
        self.assertEqual(self.settings.password_manager_enabled, False)
        parse_args(app=self.manga_reader, args=["set", "password_manager_enabled", "true"])
        self.assertEqual(self.settings.password_manager_enabled, True)

    def test_set_settings(self):
        parse_args(app=self.manga_reader, args=["set", "bundle_format", "jpg"])
        self.assertEqual(self.settings.bundle_format, "jpg")
        parse_args(app=self.manga_reader, args=["set", "bundle_format", "true"])
        self.assertEqual(self.settings.bundle_format, "true")

    def test_print_app_state(self):
        self.add_arbitrary_manga()
        chapter_id = list(self.manga_reader.get_manga_ids_in_library())[0]
        parse_args(app=self.manga_reader, args=["list-chapters", chapter_id])
        parse_args(app=self.manga_reader, args=["list"])

    def test_search(self):
        assert not len(self.manga_reader.get_manga_in_library())
        parse_args(app=self.manga_reader, args=["--auto", "search", "manga"])
        assert len(self.manga_reader.get_manga_in_library())
        self.assertRaises(ValueError, parse_args, app=self.manga_reader, args=["--auto", "search", "manga"])
