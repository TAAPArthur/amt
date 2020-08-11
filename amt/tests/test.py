from ..args import parse_args
from .test_server import TestServer
from .test_tracker import TestTracker
from ..settings import Settings
from ..app import Application
from ..media_reader import MangaReader, SERVERS, TRACKERS
from PIL import Image
import logging
import os
import shutil
import time
import unittest
from unittest.mock import patch
import sys
import requests_cache

requests_cache.core.install_cache(backend="memory", include_headers=True)


TEST_HOME = "/tmp/amt/test_home/"


logging.basicConfig(format='[%(filename)s:%(lineno)s]%(levelname)s:%(message)s', level=logging.INFO)
logger = logging.getLogger()
stream_handler = logging.StreamHandler(sys.stdout)
logger.addHandler(stream_handler)


class TestApplication(Application):
    def __init__(self):
        # Save cache in local directory
        os.putenv('XDG_CACHE_HOME', ".")
        stream_handler.stream = sys.stdout
        settings = Settings(home=TEST_HOME)
        settings.init()
        settings.shell = True
        settings.free_only = True
        settings.password_manager_enabled = False
        super().__init__([TestServer] + SERVERS, [TestTracker] + TRACKERS, settings)
        assert len(self.get_servers())
        assert all(self.get_servers())


class BaseUnitTestClass(unittest.TestCase):
    def setUp(self):
        self.app = TestApplication()
        self.media_reader = self.app
        self.settings = self.media_reader.settings
        self.test_server = self.media_reader.get_server(TestServer.id)
        assert not self.media_reader.get_media_in_library()

    def tearDown(self):
        shutil.rmtree(TEST_HOME, ignore_errors=True)

    def add_arbitrary_media(self):
        server = self.media_reader.get_server(TestServer.id)
        for media_data in server.get_media_list():
            self.media_reader.add_media(media_data)

    def add_test_media(self, no_update=False):
        media_list = self.test_server.get_media_list()
        for media_data in media_list:
            self.media_reader.add_media(media_data, no_update=no_update)
        return media_list

    def assertAllChaptersRead(self):
        self.assertTrue(all([x["read"] for media_data in self.media_reader.get_media_in_library() for x in media_data["chapters"].values()]))


class SettingsTest(BaseUnitTestClass):
    def test_settings_save_load(self):
        settings = Settings(home=TEST_HOME)
        settings.media_viewer_cmd = "dummy_cmd"
        settings.save()

        settings = Settings(home=TEST_HOME)
        assert settings.media_viewer_cmd == "dummy_cmd"

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

        settings.viewers[settings.bundle_format] = "exit 1; #{}"
        assert not settings.view(name)

    def test_get_chapter_dir_degenerate_name(self):
        settings = Settings(home=TEST_HOME)
        server = TestServer(None, settings)
        media_data = server.create_media_data("id", "Manga Name")
        server.update_chapter_data(media_data, "chapter_id", title="Degenerate Chapter Title ~//\\\\!@#$%^&*()", number="1-2")
        dir = settings.get_chapter_dir(media_data, media_data["chapters"]["chapter_id"])
        # should yield the same result everytime
        assert dir == settings.get_chapter_dir(media_data, media_data["chapters"]["chapter_id"])

    def test_get_chapter_dir(self):
        for media_data in self.test_server.get_media_list():
            self.media_reader.add_media(media_data)
            sorted_paths = sorted([(self.settings.get_chapter_dir(media_data, chapter_data), chapter_data) for chapter_data in media_data["chapters"].values()])
            sorted_chapters_by_number = sorted(media_data["chapters"].values(), key=lambda x: x["number"])
            self.assertEqual(sorted_chapters_by_number, list(map(lambda x: x[1], sorted_paths)))


class TrackerTest(BaseUnitTestClass):
    def test_get_list(self):
        for tracker in [self.media_reader.get_primary_tracker()] + self.media_reader.get_secondary_trackers():
            with self.subTest(tracker=tracker.id):
                data = tracker.get_tracker_list(id=1)
                assert data
                assert isinstance(data, list)
                assert isinstance(data[0], dict)


class ServerWorkflowsTest(BaseUnitTestClass):

    def test_media_reader_add_remove_media(self):
        for server in self.media_reader.get_servers():
            media_list = server.get_media_list()
            assert media_list
            selected_media = media_list[0]
            self.media_reader.add_media(selected_media)
            my_media_list = list(self.media_reader.get_media_in_library())
            assert 1 == len(my_media_list)
            assert my_media_list[0]["id"] == selected_media["id"]
            self.media_reader.remove_media(media_data=selected_media)
            assert 0 == len(self.media_reader.get_media_in_library())

    def test_search_media(self):
        for server in self.media_reader.get_servers():
            media_data = server.get_media_list()[0]
            name = media_data["name"]
            assert media_data == list(server.search(name))[0]
            assert server.search(name[:3])

    def test_search_for_media(self):
        servers = set()
        for term in ["a", "e", "i", "o", "u"]:
            servers |= {x["server_id"] for x in self.media_reader.search_for_media(term)}
        assert len(self.media_reader.get_servers()) == len(servers)


class ServerTest(BaseUnitTestClass):
    def test_get_media_list(self):
        for server in self.media_reader.get_servers():
            with self.subTest(server=server.id, method="get_media_list"):
                media_list = server.get_media_list()
                assert isinstance(media_list, list)
                assert all([isinstance(x, dict) for x in media_list])
            with self.subTest(server=server.id, method="search"):
                search_media_list = server.search("a")
                assert isinstance(search_media_list, list)
                assert all([isinstance(x, dict) for x in search_media_list])

            for i in (0, -1):
                media_data = media_list[i]
                with self.subTest(server=server.id, method="update_media_data", i=i):
                    return_val = server.update_media_data(media_data)
                    assert not return_val
                    assert isinstance(media_data["chapters"], dict)
                    set_of_numbers = {chapter_data["number"] for chapter_data in media_data["chapters"].values()}
                    self.assertEqual(len(set_of_numbers), len(media_data["chapters"].values()))
                    if not server.has_gaps:
                        numbers = sorted(set_of_numbers)
                        gaps = sum([numbers[i + 1] - numbers[i] > 1 for i in range(len(numbers) - 1)])
                        self.assertLessEqual(gaps, 1)

            requests_cache.core.clear()
            with self.subTest(server=server.id, method="download"):
                media_data = media_list[0]
                chapter_data = list(media_data["chapters"].values())[0]
                if not chapter_data["premium"]:
                    assert server.download_chapter(media_data, chapter_data, page_limit=1)
                assert not server.download_chapter(media_data, chapter_data, page_limit=1)

    def test_login_fail(self):
        for server in self.media_reader.get_servers():
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


@unittest.skipUnless(os.getenv("PREMIUM_TEST"), "Premium tests is not enabled")
class PremiumTest(BaseUnitTestClass):
    def test_download_premium(self):
        for server in self.media_reader.get_servers():
            if server.has_login:
                server.settings.password_manager_enabled = True
                with self.subTest(server=server.id, method="get_media_list"):
                    media_list = server.get_media_list()
                    download_passed = False
                    for media_data in media_list:
                        server.update_media_data(media_data)
                        chapter_data = next(filter(lambda x: x["premium"], media_data["chapters"].values()), None)
                        if chapter_data:
                            assert server.download_chapter(media_data, chapter_data, page_limit=1)
                            assert not server.download_chapter(media_data, chapter_data, page_limit=1)
                            download_passed = True
                            break
                    assert download_passed


class MangaReaderTest(BaseUnitTestClass):

    def test_number_servers(self):
        assert len(self.media_reader.get_servers()) > 2

    def test_save_load_cookies(self):
        key, value = "Test", "value"
        self.test_server.session.cookies.set(key, value)
        assert self.media_reader.save_session_cookies()
        self.test_server.session.cookies.set(key, "bad_value")
        assert self.media_reader.load_session_cookies()
        self.assertEqual(value, self.media_reader.session.cookies.get(key))
        self.test_server.session.cookies.set(key, "bad_value")
        assert self.media_reader.load_session_cookies()
        assert not self.media_reader.save_session_cookies()

    def test_save_load(self):
        for server in self.media_reader.get_servers():
            with self.subTest(server=server.id):
                media_list = server.get_media_list()
                self.media_reader.add_media(media_list[0])
                old_state = dict(self.media_reader.state)
                assert self.media_reader.save_state()
                assert old_state == dict(self.media_reader.state)
                self.media_reader.load_state()
                assert old_state == self.media_reader.state

    def test_mark_chapters_until_n_as_read(self):

        for server in self.media_reader.get_servers():
            with self.subTest(server=server.id):
                self.media_reader.media.clear()
                media_list = server.get_media_list()
                media_data = None
                for media_data in media_list:
                    self.media_reader.add_media(media_data)
                    if len(media_data["chapters"]) > 2:
                        break
                    self.media_reader.remove_media(media_data)
                assert len(media_data["chapters"]) > 2
                last_chapter_num = max(media_data["chapters"].values(), key=lambda x: x["number"])["number"]
                last_chapter_num_read = last_chapter_num - 1
                assert last_chapter_num > 1
                self.media_reader.mark_chapters_until_n_as_read(media_data, last_chapter_num_read)

                assert all(map(lambda x: x["read"], filter(lambda x: last_chapter_num_read >= x["number"], media_data["chapters"].values())))

                def fake_download_chapter(media_data, chapter_data):
                    assert chapter_data["number"] > last_chapter_num_read

                server.download_chapter = fake_download_chapter
                self.media_reader.download_unread_chapters()

    def test_update_no_media(self):
        assert not self.media_reader.update()

    def test_update(self):

        self.media_reader.settings.free_only = False
        for server in self.media_reader.get_servers():
            with self.subTest(server=server.id):
                media_list = server.get_media_list()
                media_data = media_list[0]
                assert not self.media_reader.update()
                new_chapters = self.media_reader.add_media(media_data)
                assert new_chapters
                assert not self.media_reader.update()

                media_data["chapters"].clear()
                new_chapters2 = self.media_reader.update_media(media_data)
                assert new_chapters == new_chapters2

    def test_update_download(self):
        for server in self.media_reader.get_servers():
            if not server.has_free_chapters:
                continue
            with self.subTest(server=server.id):
                media_list = server.get_media_list()
                for media_data in media_list:
                    self.media_reader.add_media(media_data, no_update=True)
                    chapter_list = self.media_reader.update_media(media_data, download=True, limit=1, page_limit=3)
                    if chapter_list:
                        chapter_data = chapter_list[0]
                        break
                min_chapter = min(media_data["chapters"].values(), key=lambda x: x["number"])
                assert min_chapter == chapter_data
                dir_path = self.media_reader.settings.get_chapter_dir(media_data, chapter_data)

                dirpath, dirnames, filenames = list(os.walk(dir_path))[0]
                assert filenames
                for file_name in filenames:
                    with open(os.path.join(dirpath, file_name), "rb") as img_file:
                        Image.open(img_file)

                # error if we try to save a page we have already downloaded
                server.save_chapter_page = None
                assert not server.download_chapter(media_data, chapter_data, page_limit=3)

    def test_preserve_read_status_on_update(self):
        media_list = self.add_test_media()
        self.media_reader.mark_up_to_date()
        for i in range(2):
            for media_data in media_list:
                assert all(map(lambda x: x["read"], media_data["chapters"].values()))
            self.media_reader.update()

    def test_mark_up_to_date(self):
        media_list = self.add_test_media()
        self.media_reader.mark_up_to_date(self.test_server.id)
        for media_data in media_list:
            assert all(map(lambda x: x["read"], media_data["chapters"].values()))
        self.media_reader.mark_up_to_date(self.test_server.id, 1)
        for media_data in media_list:
            assert all(map(lambda x: x["read"], media_data["chapters"].values()))
        self.media_reader.mark_up_to_date(self.test_server.id, 1, force=True)
        for media_data in media_list:
            chapter_list = list(sorted(media_data["chapters"].values(), key=lambda x: x["number"]))
            assert all(map(lambda x: x["read"], chapter_list[:-1]))
            assert not chapter_list[-1]["read"]

    def test_download_chapters_partial(self):
        server = self.test_server
        media_list = server.get_media_list()
        for media_data in media_list:
            self.media_reader.add_media(media_data)
            self.assertEqual(1, self.media_reader.download_chapters(media_data, 1))

    def _prepare_for_bundle(self):
        server = self.media_reader.get_server(TestServer.id)
        media_list = server.get_media_list()
        num_chapters = 0
        for media_data in media_list:
            self.media_reader.add_media(media_data)
            num_chapters += len(media_data["chapters"])

        self.assertEqual(num_chapters, self.media_reader.download_unread_chapters())

        self.settings.bundle_cmds[self.settings.bundle_format] = "echo {} > {}"
        self.settings.viewers[self.settings.bundle_format] = "echo {}"

    def test_bundle(self):
        self._prepare_for_bundle()
        name = self.media_reader.bundle_unread_chapters()
        assert self.media_reader.read_bundle(name)
        assert all([x["read"] for media_data in self.media_reader.get_media_in_library() for x in media_data["chapters"].values()])

    def test_bundle_shuffle(self):
        self._prepare_for_bundle()
        names = set()
        for i in range(10):
            names.add(self.media_reader.bundle_unread_chapters(shuffle=True))
        assert all(names)
        assert len(names) > 1

    def test_bundle_no_unreads(self):
        assert not self.media_reader.bundle_unread_chapters()

    def test_bundle_fail(self):
        self._prepare_for_bundle()
        self.settings.viewers[self.settings.bundle_format] = "exit 1; echo {};"
        assert not self.media_reader.read_bundle("none.{}".format(self.settings.bundle_format))
        assert not any([x["read"] for media_data in self.media_reader.get_media_in_library() for x in media_data["chapters"].values()])


class ApplicationTest(BaseUnitTestClass):

    def test_list(self):
        self.add_arbitrary_media()
        self.app.list()

    def test_list_chapters(self):
        self.add_arbitrary_media()
        for id in self.media_reader.get_media_ids_in_library():
            self.app.list_chapters(id)

    @patch('builtins.input', return_value='0')
    def test_search_add(self, input):
        media_data = self.app.search_add("media")
        assert(media_data)
        assert media_data in self.media_reader.get_media_in_library()

    @patch('builtins.input', return_value='a')
    def test_search_add_nan(self, input):
        assert not self.app.search_add("media")

    @patch('builtins.input', return_value='1000')
    def test_search_add_out_or_range(self, input):
        assert not self.app.search_add("media")

    @patch('builtins.input', return_value='0')
    def test_load_from_tracker(self, input):
        c, n = self.app.load_from_tracker(1)
        assert c
        self.assertEqual(n, c)
        c2, n2 = self.app.load_from_tracker(1)
        self.assertEqual(c, c2)
        self.assertEqual(0, n2)


class ArgsTest(BaseUnitTestClass):
    @patch('builtins.input', return_value='0')
    def test_arg(self, input):
        parse_args(app=self.media_reader, args=["auth"])

    def test_get_settings(self):
        parse_args(app=self.media_reader, args=["get", "password_manager_enabled"])

    def test_set_settings_bool(self):
        parse_args(app=self.media_reader, args=["set", "password_manager_enabled", "false"])
        self.assertEqual(self.settings.password_manager_enabled, False)
        parse_args(app=self.media_reader, args=["set", "password_manager_enabled", "true"])
        self.assertEqual(self.settings.password_manager_enabled, True)

    def test_set_settings(self):
        parse_args(app=self.media_reader, args=["set", "bundle_format", "jpg"])
        self.assertEqual(self.settings.bundle_format, "jpg")
        parse_args(app=self.media_reader, args=["set", "bundle_format", "true"])
        self.assertEqual(self.settings.bundle_format, "true")

    def test_print_app_state(self):
        self.add_arbitrary_media()
        chapter_id = list(self.media_reader.get_media_ids_in_library())[0]
        parse_args(app=self.media_reader, args=["list-chapters", chapter_id])
        parse_args(app=self.media_reader, args=["list"])

    def test_search_save(self):
        assert not len(self.media_reader.get_media_in_library())
        parse_args(app=self.media_reader, args=["--auto", "search", "media"])
        assert len(self.media_reader.get_media_in_library())
        self.app.load_state()
        assert len(self.media_reader.get_media_in_library())

    def test_load(self):
        parse_args(app=self.media_reader, args=["--auto", "search", "media"])
        media_id = next(iter(self.media_reader.get_media_ids_in_library()))
        parse_args(app=self.media_reader, args=["--auto", "load", "test_user"])
        assert self.media_reader.get_tracker_info(media_id, self.media_reader.get_primary_tracker().id)

    def test_sync_progress(self):
        parse_args(app=self.media_reader, args=["--auto", "load"])
        parse_args(app=self.media_reader, args=["mark-up-to-date"])
        parse_args(app=self.media_reader, args=["sync"])
        self.media_reader.media.clear()
        parse_args(app=self.media_reader, args=["--auto", "load"])
        for media_data in self.media_reader.get_media_in_library():
            self.assertEqual(self.media_reader.get_last_chapter_number(media_data), self.media_reader.get_last_read(media_data))

    def test_download(self):
        media_list = self.add_test_media(True)
        assert len(media_list[0]["chapters"]) == 0
        parse_args(app=self.media_reader, args=["-u", "download"])
        assert len(media_list[0]["chapters"])
        self.assertEqual(0, self.app.download_chapters(media_list[0]))

    def test_download_next(self):
        media_list = self.add_test_media()
        for id, media_data in self.media_reader.media.items():
            server = self.app.get_server(media_data["server_id"])
            chapter = sorted(media_data["chapters"].values(), key=lambda x: x["number"])[0]
            parse_args(app=self.media_reader, args=["download-next", id, "1"])
            self.assertEqual(0, server.download_chapter(media_data, chapter))

    def test_update(self):
        media_list = self.add_test_media(True)
        assert len(media_list[0]["chapters"]) == 0
        parse_args(app=self.media_reader, args=["update"])
        assert len(media_list[0]["chapters"])

    def test_search(self):
        assert not len(self.media_reader.get_media_in_library())
        parse_args(app=self.media_reader, args=["--auto", "search", "media"])
        assert len(self.media_reader.get_media_in_library())
        self.assertRaises(ValueError, parse_args, app=self.media_reader, args=["--auto", "search", "media"])

    def test_bundle_read(self):
        self.settings.bundle_cmds[self.settings.bundle_format] = "echo {}; touch {}"
        self.settings.viewers[self.settings.bundle_format] = "ls {}"
        media_list = self.add_test_media()
        parse_args(app=self.media_reader, args=["bundle"])
        assert len(self.app.bundles)
        name, bundle_data = list(self.app.bundles.items())[0]
        self.assertTrue(os.path.isabs(name))
        self.assertTrue(os.path.exists(name))
        self.assertEqual(len(bundle_data), sum([len(x["chapters"]) for x in media_list]))
        parse_args(app=self.media_reader, args=["read", os.path.basename(name)])
        self.assertAllChaptersRead()

    def test_bundle_specific(self):
        self.settings.bundle_cmds[self.settings.bundle_format] = "echo {}; touch {}"
        media_list = self.add_test_media()
        num_chapters = sum([len(x["chapters"]) for x in media_list])
        fake_data = self.test_server.create_media_data("-1", "Fake Data")
        fake_data["server_id"] = "unique_id"
        self.test_server.update_chapter_data(fake_data, 1, "Fake chapter", 1)
        self.media_reader.add_media(fake_data, no_update=True)
        parse_args(app=self.media_reader, args=["bundle", self.test_server.id])
        self.assertEqual(len(list(self.app.bundles.values())[0]), num_chapters)
        self.app.bundles.clear()
        media_data = media_list[0]
        for name in (media_data["name"], self.app._get_global_id(media_data)):
            parse_args(app=self.media_reader, args=["bundle", str(name)])
            self.assertEqual(len(list(self.app.bundles.values())[0]), len(media_data["chapters"]))
            self.app.bundles.clear()
