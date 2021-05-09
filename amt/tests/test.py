import inspect
import logging
import os
import re
import shutil
import subprocess
import sys
import unittest
from inspect import findsource
from unittest.mock import patch

from PIL import Image

from .. import servers, tests
from ..app import Application
from ..args import parse_args
from ..media_reader import SERVERS, TRACKERS, import_sub_classes
from ..server import ANIME, MANGA, MEDIA_TYPES, NOVEL
from ..servers.custom import CustomServer, get_local_server_id
from ..settings import Settings
from .test_server import (TEST_BASE, TestAnimeServer, TestServer,
                          TestServerLogin)
from .test_tracker import TestTracker

TEST_HOME = TEST_BASE + "test_home/"


logging.basicConfig(format="[%(filename)s:%(lineno)s]%(levelname)s:%(message)s", level=logging.INFO)

TEST_SERVERS = set()
TEST_TRACKERS = set()
LOCAL_SERVERS = set()

import_sub_classes(tests, TestServer, TEST_SERVERS)
import_sub_classes(tests, TestTracker, TEST_TRACKERS)
import_sub_classes(servers, CustomServer, LOCAL_SERVERS)


class TestApplication(Application):
    def __init__(self, real=False, local=False):
        # Save cache in local directory
        os.environ["XDG_CACHE_HOME"] = "./.cache"
        settings = Settings(home=TEST_HOME)
        del os.environ["XDG_CACHE_HOME"]
        if os.path.exists(settings.get_cookie_file()):
            os.remove(settings.get_cookie_file())
        settings.env_override_prefix = None
        settings.free_only = True
        settings.no_save_session = True
        settings.no_load_session = True
        settings.password_manager_enabled = False
        settings.shell = True
        settings.threads = 0

        _servers = list(TEST_SERVERS)
        _trackers = list(TEST_TRACKERS)
        if real:
            settings.threads = Settings.threads
            if os.getenv("ENABLE_ONLY_SERVERS"):
                enabled_servers = set(os.getenv("ENABLE_ONLY_SERVERS").split(","))
                _servers = [x for x in SERVERS if x.id in enabled_servers]
            else:
                _servers = [s for s in SERVERS if not s.external]
            _trackers += TRACKERS
        elif local:
            settings.js_enabled_browser = ""
            _servers += LOCAL_SERVERS

        super().__init__(_servers, _trackers, settings)
        assert len(self.get_servers()) == len(_servers)
        assert len(self.get_trackers()) == len(_trackers)
        assert len(self.get_trackers()) == 1 + len(self.get_secondary_trackers())

        self.settings.suppress_cmd_output = True
        self.settings.anime_viewer = "echo {media} {title}"
        self.settings.manga_viewer = "[ -f {} ]"
        self.settings.novel_viewer = "[ -f {} ]"
        self.settings.segment_viewer = "ls {media}; echo {title}"
        self.settings.page_viewer = "ls {}"
        self.settings.bundle_cmds[self.settings.bundle_format] = "ls {files}; touch {name}"


class BaseUnitTestClass(unittest.TestCase):
    real = False
    local = False

    def __init__(self, methodName="runTest"):
        super().__init__(methodName=methodName)
        self.init()

    def init(self):
        pass

    def setUp(self):
        self.stream_handler = logging.StreamHandler(sys.stdout)
        logger = logging.getLogger()
        logger.handlers = []
        logger.addHandler(self.stream_handler)
        shutil.rmtree(TEST_HOME, ignore_errors=True)
        self.app = TestApplication(self.real, self.local)
        self.media_reader = self.app
        self.settings = self.media_reader.settings
        self.test_server = self.media_reader.get_server(TestServer.id)
        self.test_anime_server = self.media_reader.get_server(TestAnimeServer.id)
        assert not self.media_reader.get_media_in_library()

    def tearDown(self):
        shutil.rmtree(TEST_HOME, ignore_errors=True)
        self.app.session.close()
        logging.getLogger().removeHandler(self.stream_handler)

    def add_arbitrary_media(self):
        server = self.media_reader.get_server(TestServer.id)
        for media_data in server.get_media_list():
            self.media_reader.add_media(media_data)

    def add_test_media(self, server=None, no_update=False):
        media_list = server.get_media_list() if server else self.test_server.get_media_list() + self.test_anime_server.get_media_list() + self.media_reader.get_server(TestServerLogin.id).get_media_list()
        for media_data in media_list:
            self.media_reader.add_media(media_data, no_update=no_update)
        assert media_list
        return media_list

    def getChapters(self, media_type=ANIME | MANGA):
        return [x for media_data in self.media_reader.get_media_in_library() for x in media_data["chapters"].values() if media_data["media_type"] & media_type]

    def assertAllChaptersRead(self, media_type=None):
        return all(map(lambda x: x["read"], self.getChapters(media_type)))

    def getNumChaptersRead(self, media_type=ANIME | MANGA):
        return sum(map(lambda x: x["read"], self.getChapters(media_type)))

    def verify_download(self, media_data, chapter_data, skip_file_type_validation=False):
        server = self.media_reader.get_server(media_data["server_id"])
        if server.external:
            return
        valid_image_formats = ("png", "jpeg", "jpg")
        assert server.is_fully_downloaded(media_data, chapter_data)
        dir_path = self.media_reader.settings.get_media_dir(media_data)
        for dirpath, dirnames, filenames in os.walk(dir_path):
            for file_name in filenames:
                assert len(filenames) > 1, f"files: {filenames}, dirnames: {dirnames}"
                if not file_name.startswith("."):
                    path = os.path.join(dir_path, dirpath, file_name)
                    assert os.path.exists(path)
                    if skip_file_type_validation:
                        continue
                    if media_data["media_type"] == MANGA:
                        with open(path, "rb") as img_file:
                            img = Image.open(img_file)
                            self.assertIn(img.format.lower(), valid_image_formats)
                            self.assertIn(file_name.split(".")[-1], valid_image_formats)
                    elif media_data["media_type"] == ANIME:
                        subprocess.check_call(["ffprobe", "-loglevel", "quiet", path])

    def getAllChapters(self):
        for media_data in self.app._get_media():
            server = self.app.get_server(media_data["server_id"])
            for chapter in sorted(media_data["chapters"].values(), key=lambda x: x["number"]):
                yield server, media_data, chapter

    def verifyAllChaptersDownloaded(self):
        for server, media_data, chapter in self.getAllChapters():
            self.assertTrue(server.is_fully_downloaded(media_data, chapter))

    def verifyNoChaptersDownloaded(self):
        for server, media_data, chapter in self.getAllChapters():
            self.assertFalse(server.is_fully_downloaded(media_data, chapter))

    def verify_unique_numbers(self, chapters):
        list_of_numbers = sorted([chapter_data["number"] for chapter_data in chapters.values() if not chapter_data["special"]])
        set_of_numbers = sorted(list(set(list_of_numbers)))
        self.assertEqual(set_of_numbers, list_of_numbers)
        return set_of_numbers

    def assertTrueOrSkipTest(self, obj):
        if os.getenv("ENABLE_ONLY_SERVERS") and not obj:
            self.skipTest("Server not enabled")
        assert obj


class MinimalUnitTestClass(BaseUnitTestClass):
    def init(self):
        self.local = True


@unittest.skipIf(os.getenv("QUICK"), "Real servers are disabled")
class RealBaseUnitTestClass(BaseUnitTestClass):
    def init(self):
        self.real = True


class SettingsTest(BaseUnitTestClass):

    separators = ("\t", "\n", "\r", "some_string")

    def setUp(self):
        super().setUp()
        self.settings.password_manager_enabled = True
        self.settings.password_load_cmd = "cat {}{} 2>/dev/null".format(TEST_HOME, "{}")
        self.settings.password_save_cmd = r"cat - > {}{}".format(TEST_HOME, "{}")

    def test_settings_save_load(self):
        self.settings.password_save_cmd = "dummy_cmd"
        self.settings.save()

        assert Settings(home=TEST_HOME).password_save_cmd == "dummy_cmd"

    def test_settings_no_load_js_cookies(self):
        self.settings.js_enabled_browser = False
        assert not self.settings.load_js_cookies(None, None)

    def test_credentials(self):
        server_id = "test"
        assert not self.settings.get_credentials(server_id)
        username, password = "user", "pass"
        self.settings.store_credentials(server_id, username, password)
        assert (username, password) == self.settings.get_credentials(server_id)
        tracker_id = "test-tracker"
        assert not self.settings.get_credentials(tracker_id)
        assert not self.settings.get_secret(tracker_id)
        secret = "MySecret"
        self.settings.store_secret(tracker_id, secret)
        assert secret == self.settings.get_secret(tracker_id)

    def test_credentials_seperator(self):

        username, password = "user", "pass"
        for sep in self.separators:
            self.settings.credential_separator = sep
            with self.subTest(sep=sep):
                self.settings.store_credentials(TestServer.id, username, password)
                self.assertEqual((username, password), self.settings.get_credentials(TestServer.id))

    def test_credentials_override(self):
        self.settings.env_override_prefix = "prefix"
        server_id = "test"
        username, password = "user", "pass"
        for sep in self.separators:
            self.settings.credential_separator = sep
            with self.subTest(sep=sep):
                os.environ[self.settings.env_override_prefix + server_id] = f"{username}{sep}{password}"
                try:
                    self.assertEqual(username, self.settings.get_credentials(server_id)[0])
                    self.assertEqual(password, self.settings.get_credentials(server_id)[1])
                    assert not self.settings.get_credentials("bad_id")
                finally:
                    del os.environ[self.settings.env_override_prefix + server_id]

    def test_bundle(self):
        name = self.settings.bundle("")
        assert name.endswith("." + self.settings.bundle_format)
        assert self.settings.open_manga_viewer(name)

        self.settings.manga_viewer = "exit 1; #{}"
        assert not self.settings.open_manga_viewer(name)

    def test_get_chapter_dir_degenerate_name(self):
        server = TestServer(None, self.settings)
        media_data = server.create_media_data("id", "Manga Name")
        server.update_chapter_data(media_data, "chapter_id", title="Degenerate Chapter Title ~//\\\\!@#$%^&*()", number="1-2")
        dir = self.settings.get_chapter_dir(media_data, media_data["chapters"]["chapter_id"])
        # should yield the same result everytime
        assert dir == self.settings.get_chapter_dir(media_data, media_data["chapters"]["chapter_id"])

    def test_get_chapter_dir(self):
        for media_data in self.test_server.get_media_list():
            self.media_reader.add_media(media_data)
            sorted_paths = sorted([(self.settings.get_chapter_dir(media_data, chapter_data), chapter_data) for chapter_data in media_data["chapters"].values()])
            sorted_chapters_by_number = sorted(media_data["chapters"].values(), key=lambda x: x["number"])
            self.assertEqual(sorted_chapters_by_number, list(map(lambda x: x[1], sorted_paths)))


class ServerWorkflowsTest(BaseUnitTestClass):

    def test_media_reader_add_remove_media(self):
        for server in self.media_reader.get_servers():
            with self.subTest(server=server.id):
                media_list = server.get_media_list()
                assert media_list
                selected_media = media_list[0]
                self.media_reader.add_media(selected_media)
                my_media_list = list(self.media_reader.get_media_in_library())
                assert 1 == len(my_media_list)
                assert my_media_list[0]["id"] == selected_media["id"]
                self.media_reader.remove_media(media_data=selected_media)
                assert 0 == len(self.media_reader.get_media_in_library())

    def test_server_download(self):
        for server in self.media_reader.get_servers():
            for media_data in server.get_media_list():
                with self.subTest(server=server.id, media_data=media_data["name"]):
                    server.update_media_data(media_data)
                    chapter_data = list(media_data["chapters"].values())[0]
                    self.assertEqual(True, server.download_chapter(media_data, chapter_data, page_limit=2))
                    self.verify_download(media_data, chapter_data)

    def test_search_media(self):
        for server in self.media_reader.get_servers():
            with self.subTest(server=server.id):
                media_data = server.get_media_list()[0]
                name = media_data["name"]
                assert media_data == list(server.search(name))[0]
                assert server.search(name[:3])

    def download_matching_chapters(self, server, func):
        for media in server.get_media_list():
            server.update_media_data(media)
            chapters = list(filter(func, media["chapters"].values()))
            if chapters:
                server.download_chapter(media_data=media, chapter_data=chapters[0])

    def test_bad_login(self):
        server = self.media_reader.get_server(TestServerLogin.id)
        server.fail_login = True
        server.settings.password_manager_enabled = True
        server.settings.password_load_cmd = r"echo -e A\\tB"
        self.assertRaises(ValueError, self.download_matching_chapters, server, lambda x: x["premium"])
        self.assertEqual(1, server.counter)

    def test_server_download_inaccessiable(self):
        server = self.media_reader.get_server(TestServerLogin.id)
        server.inaccessible = True
        self.assertRaises(ValueError, self.download_matching_chapters, server, lambda x: x["inaccessible"])
        self.assertEqual(0, server.counter)


class MediaReaderTest(BaseUnitTestClass):

    def test_load_cookies_no_exists(self):
        self.app.settings.no_load_session = False
        if os.path.exists(self.app.settings.get_cookie_file()):
            os.remove(self.app.settings.get_cookie_file())
        self.media_reader.load_session_cookies()

    def test_load_cookies_session_cookies(self):
        self.app.settings.no_load_session = False
        name, value = "Test", "value"
        name2, value2 = "Test2", "value2"
        self.settings.cookie_files = []
        with open(self.settings.get_cookie_file(), "w") as f:
            f.write("\t".join([TestServer.domain, "TRUE", "/", "FALSE", "1640849596", name, value, "None"]))
            f.write("\n")
            f.write("\t".join([f"#HttpOnly_.{TestServer.domain}", "TRUE", "/", "FALSE", "1640849596", name2, value2, "None"]))

        self.media_reader.load_session_cookies()
        assert self.app.session.cookies
        self.assertEqual(value, self.media_reader.session.cookies.get(name))
        self.assertEqual(value2, self.media_reader.session.cookies.get(name2))

    def test_save_load_cookies(self):
        self.app.settings.no_load_session = False
        self.app.settings.no_save_session = False
        key, value = "Test", "value"
        self.test_server.add_cookie(key, value)
        assert self.media_reader.save_session_cookies()
        self.test_server.add_cookie(key, "bad_value")
        self.media_reader.load_session_cookies()
        self.assertEqual(value, self.media_reader.session.cookies.get(key))
        self.test_server.add_cookie(key, "bad_value")
        self.media_reader.load_session_cookies()
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

    def test_save_load_global_id_format_change(self):
        media_list = self.add_test_media()
        assert self.media_reader.save_state()
        self.media_reader._get_global_id = lambda x: "!{}/{}".format(x["server_id"], x["id"])
        self.media_reader.load_state()
        self.assertEquals(set(map(self.media_reader._get_global_id, self.media_reader.get_media_in_library())), self.media_reader.get_media_ids_in_library())
        self.assertEquals(len(media_list), len(self.media_reader.get_media_ids_in_library()))

    def test_save_load_disabled(self):
        self.add_test_media()
        assert self.media_reader.save_state()
        temp = self.media_reader._servers
        self.media_reader._servers = {}
        self.media_reader.load_state()
        assert not len(self.media_reader.media)
        self.media_reader.save_state()
        self.media_reader._servers = temp
        self.media_reader.load_state()
        assert len(self.media_reader.media)

    def test_mark_chapters_until_n_as_read(self):

        for server in self.media_reader.get_servers():
            with self.subTest(server=server.id):
                self.media_reader.media.clear()
                media_list = server.get_media_list()
                media_data = media_list[0]
                self.media_reader.add_media(media_data)
                assert len(media_data["chapters"]) > 2
                last_chapter_num = max(media_data["chapters"].values(), key=lambda x: x["number"])["number"]
                last_chapter_num_read = last_chapter_num - 1
                assert last_chapter_num > 1
                self.media_reader.mark_chapters_until_n_as_read(media_data, last_chapter_num_read)

                assert all(map(lambda x: x["read"], filter(lambda x: last_chapter_num_read >= x["number"], media_data["chapters"].values())))

                def fake_download_chapter(media_data, chapter_data):
                    assert chapter_data["number"] > last_chapter_num_read
                    return True

                server.download_chapter = fake_download_chapter
                self.media_reader.download_unread_chapters()

    def test_download_unread_chapters(self):
        media_list = self.add_test_media()
        count = self.media_reader.download_unread_chapters()

        self.assertEqual(count, sum([len(media_data["chapters"]) for media_data in media_list]))

        for media_data in media_list:
            for chapter_data in media_data["chapters"].values():
                self.verify_download(media_data, chapter_data, skip_file_type_validation=True)

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

    def test_update_hidden_media(self):
        media_list = self.add_test_media(server=self.test_server)
        self.test_server.hide = True
        numMedia = len(media_list)
        initialChapters = len(self.getChapters())
        assert not self.media_reader.update()
        self.assertEquals(numMedia, len(self.app.get_media_in_library()))
        self.assertEquals(initialChapters, len(self.getChapters()))
        self.test_server.sync_removed = True
        assert not self.media_reader.update()
        self.assertEquals(0, len(self.getChapters()))

    def test_update_download(self):
        for server in self.media_reader.get_servers():
            with self.subTest(server=server.id):
                media_list = server.get_media_list()
                for media_data in media_list:
                    self.media_reader.add_media(media_data, no_update=True)
                    chapter_list = self.media_reader.update_media(media_data, download=True, media_type_to_download=None, limit=1, page_limit=3)
                    if chapter_list:
                        chapter_data = chapter_list[0]
                        break
                min_chapter = min(media_data["chapters"].values(), key=lambda x: x["number"])
                assert min_chapter == chapter_data

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
        media_list = self.add_test_media(self.test_server)
        self.media_reader.mark_up_to_date(self.test_server.id)
        for media_data in media_list:
            assert all(map(lambda x: x["read"], media_data["chapters"].values()))
        self.media_reader.mark_up_to_date(self.test_server.id, N=-1)
        for media_data in media_list:
            assert all(map(lambda x: x["read"], media_data["chapters"].values()))
        self.media_reader.mark_up_to_date(self.test_server.id, N=-1, force=True)
        for media_data in media_list:
            chapter_list = list(sorted(media_data["chapters"].values(), key=lambda x: x["number"]))
            assert all(map(lambda x: x["read"], chapter_list[:-1]))
            assert not chapter_list[-1]["read"]

    def test_download_chapters_partial(self):
        server = self.test_server
        media_list = server.get_media_list()
        for media_data in media_list:
            with self.subTest(media_id=media_data["id"], name=media_data["name"]):
                self.media_reader.add_media(media_data)
                self.assertEqual(1, self.media_reader.download_chapters(media_data, 1))

    def _prepare_for_bundle(self, id=TestServer.id, no_download=False):
        server = self.media_reader.get_server(id)
        media_list = server.get_media_list()
        num_chapters = 0
        for media_data in media_list:
            self.media_reader.add_media(media_data)
            num_chapters += len(media_data["chapters"])

        if not no_download:
            self.assertEqual(num_chapters, self.media_reader.download_unread_chapters())

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
        assert names
        assert all(names)
        assert len(names) > 1

    def test_bundle_no_unreads(self):
        assert not self.media_reader.bundle_unread_chapters()

    def test_bundle_fail(self):
        self._prepare_for_bundle()
        self.settings.manga_viewer = "exit 1; # {};"
        assert not self.media_reader.read_bundle("none.{}".format(self.settings.bundle_format))
        assert not any([x["read"] for media_data in self.media_reader.get_media_in_library() for x in media_data["chapters"].values()])

    def test_bundle_anime(self):
        self._prepare_for_bundle(TestAnimeServer.id)
        self.assertFalse(self.media_reader.bundle_unread_chapters())

    def test_view_chapters(self):
        self._prepare_for_bundle(TestServer.id)
        assert self.app.view_chapters()
        self.assertAllChaptersRead(MANGA)

    def test_view_chapters_fail(self):
        self.settings.page_viewer = "exit 1; # {};"
        self._prepare_for_bundle(TestServer.id)
        assert not self.app.view_chapters()

    def test_stream_anime_bad_url(self):
        assert not self.media_reader.stream("bad_url")

    def test_play_anime(self):
        self._prepare_for_bundle(TestAnimeServer.id, no_download=True)
        assert self.media_reader.play(cont=True)
        assert all([x["read"] for media_data in self.media_reader.get_media_in_library() for x in media_data["chapters"].values()])

    def test_play_offset_anime(self):
        self._prepare_for_bundle(TestAnimeServer.id, no_download=True)
        self.media_reader.offset(TestAnimeServer.id, 1)
        self.media_reader.update()
        chapters = [x for media_data in self.media_reader.get_media_in_library() for x in media_data["chapters"].values()]
        assert chapters
        assert [x["read"] for x in chapters if x["number"] <= 0]
        assert self.media_reader.play(cont=True)

        assert all([x["read"] for x in chapters if x["number"] > 0])
        assert not any([x["read"] for x in chapters if x["number"] <= 0])
        assert self.media_reader.play(cont=True, any_unread=True)
        assert all([x["read"] for x in chapters])

    def test_play_anime_downloaded(self):
        self._prepare_for_bundle(TestAnimeServer.id, no_download=False)
        assert self.media_reader.play(cont=True)
        assert all([x["read"] for media_data in self.media_reader.get_media_in_library() for x in media_data["chapters"].values()])

    def test_play_anime_single(self):
        self._prepare_for_bundle(TestAnimeServer.id, no_download=True)
        assert self.media_reader.play()
        read_dist = [((x["id"], x["number"]), x["read"]) for media_data in self.media_reader.get_media_in_library() for x in media_data["chapters"].values()]
        read_dist.sort()
        self.assertEqual(1, sum(map(lambda x: x[1], read_dist)))
        self.assertTrue(read_dist[0][1])


class ApplicationTest(BaseUnitTestClass):

    def test_list(self):
        self.add_arbitrary_media()
        self.app.list()

    def test_list_chapters(self):
        self.add_arbitrary_media()
        for id in self.media_reader.get_media_ids_in_library():
            self.app.list_chapters(id)

    @patch("builtins.input", return_value="0")
    def test_search_add(self, input):
        media_data = self.app.search_add("a")
        assert(media_data)
        assert media_data in self.media_reader.get_media_in_library()

    @patch("builtins.input", return_value="a")
    def test_search_add_nan(self, input):
        assert not self.app.search_add("a")

    @patch("builtins.input", return_value="1000")
    def test_search_add_out_or_range(self, input):
        assert not self.app.search_add("a")

    @patch("builtins.input", return_value="0")
    def test_load_from_tracker(self, input):
        c, n = self.app.load_from_tracker(1)
        assert c
        self.assertEqual(n, c)
        c2, n2 = self.app.load_from_tracker(1)
        self.assertEqual(c, c2)
        self.assertEqual(0, n2)

    def test_select_chapter(self):
        self.app.auto_select = True
        for mediaName in ("Manga", "Anime"):
            with self.subTest(mediaName=mediaName):
                self.assertTrue(self.app.select_chapter(mediaName))


class ApplicationTestWithErrors(BaseUnitTestClass):
    def setUp(self):
        super().setUp()
        self.app.auto_select = True

    def test_search_with_error(self):
        self.test_server.inject_error()
        assert self.app.search_add("manga")
        assert self.test_server.was_error_thrown()

    def test_update_with_error(self):
        self.add_test_media(no_update=True)
        self.test_server.inject_error()
        assert self.app.update()
        assert self.test_server.was_error_thrown()

    def test_download_with_error(self):
        self.add_test_media()
        self.test_server.inject_error()
        assert self.app.download_unread_chapters()
        assert self.test_server.was_error_thrown()


class RealArgsTest(RealBaseUnitTestClass):
    def test_circumvent_bot_protection(self):
        self.settings.js_enabled_browser = True
        parse_args(app=self.media_reader, args=["js-cookie-parser"])
        for server in self.app.get_servers():
            if server.domain:
                server.session_get_protected("https://" + server.domain)

    @unittest.skipIf(os.getenv("ENABLE_ONLY_SERVERS"), "Not all servers are enabled")
    def test_load_from_tracker(self):
        anime = ["HAIKYU!! To the Top", "Kaij: Ultimate Survivor", "Re:Zero", "Steins;Gate"]
        self.app.get_primary_tracker().set_custom_anime_list(anime)
        parse_args(app=self.media_reader, args=["--auto", "load", "--media-type=ANIME"])
        self.assertEqual(len(anime), len(self.media_reader.get_media_ids_in_library()))


class CustomTest(MinimalUnitTestClass):
    def setUp(self):
        super().setUp()
        self.setup_customer_server_data()

    def setup_customer_server_data(self):

        for media_type in (MANGA, ANIME, NOVEL):
            local_server_id = get_local_server_id(media_type)
            dir = self.settings.get_server_dir(local_server_id)
            image = Image.new("RGB", (100, 100))
            for media_name in ["A", "B", "C"]:
                parent_dir = os.path.join(dir, media_name)
                for chapter_name in ["01.", "2.0 Chapter Tile", "3 Chapter_Title", "4"]:
                    chapter_dir = os.path.join(parent_dir, chapter_name)
                    os.makedirs(chapter_dir)
                    image.save(os.path.join(chapter_dir, "image"), "jpeg")

            for bundled_media_name in ["A_Bundled", "B_Bundled", "C_Bundled"]:
                parent_dir = os.path.join(dir, bundled_media_name)
                os.makedirs(parent_dir)
                for chapter_name in ["10", "Episode 2"]:
                    image.save(os.path.join(parent_dir, chapter_name), "jpeg")

    def test_custom_bundle(self):
        server = self.media_reader.get_server(get_local_server_id(MANGA))
        self.add_test_media(server)
        self.assertTrue(self.media_reader.bundle_unread_chapters())

    def test_custom_update(self):
        server = self.media_reader.get_server(get_local_server_id(MANGA))
        media_list = self.add_test_media(server)
        assert media_list
        for media_data in media_list:
            assert not self.app.update_media(media_data)


class ArgsTest(MinimalUnitTestClass):
    @patch("builtins.input", return_value="0")
    def test_arg(self, input):
        parse_args(app=self.media_reader, args=["auth"])

    def test_test_login(self):
        server = self.app.get_server(TestServerLogin.id)
        assert server.needs_authentication()
        parse_args(app=self.media_reader, args=["login", "--server", server.id])
        assert not server.needs_authentication()
        server.reset()
        assert server.needs_authentication()
        parse_args(app=self.media_reader, args=["login"])
        assert not server.needs_authentication()

    def test_test_login_fail(self):
        server = self.app.get_server(TestServerLogin.id)
        server.fail_login = True
        parse_args(app=self.media_reader, args=["login", "--server", server.id])
        assert server.needs_authentication()

    def test_autocomplete_not_found(self):
        with patch.dict(sys.modules, {"argcomplete": None}):
            parse_args(app=self.media_reader, args=["list"])

    def test_cookies(self):
        key, value = "Key", "value"
        parse_args(app=self.media_reader, args=["add-cookie", TestServer.id, key, value])
        self.assertEqual(self.app.session.cookies.get(key), value)
        parse_args(app=self.media_reader, args=["--clear-cookies", "list"])
        self.assertNotEqual(self.app.session.cookies.get(key), value)

    def test_js_cookie_parser(self):
        parse_args(app=self.media_reader, args=["js-cookie-parser"])

    def test_incap_cookies(self):
        value = "value"
        self.app.session.cookies.clear()
        parse_args(app=self.media_reader, args=["add-incapsula", TestAnimeServer.id, value])
        self.assertEqual(list(self.app.session.cookies.values())[0], value)

    def test_get_settings(self):
        parse_args(app=self.media_reader, args=["setting", "password_manager_enabled"])

    def test_set_settings(self):
        key_values = [("bundle_format", "jpg"), ("bundle_format", "true"),
                      ("max_retires", "1", 1),
                      ("max_retires", "2", 2),
                      ("password_manager_enabled", "true", True),
                      ("password_manager_enabled", "false", False)]

        self.app.settings.save()
        for key_value in key_values:
            parse_args(app=self.media_reader, args=["setting", key_value[0], key_value[1]])
            self.assertEqual(self.settings.get(key_value[0]), key_value[-1])
            self.app.settings.load()
            self.assertEqual(self.settings.get(key_value[0]), key_value[-1])

    @patch("getpass.getpass", return_value="0")
    def test_set_password(self, input):
        self.app.settings.password_manager_enabled = True
        self.app.settings.password_load_cmd = "cat {}{} 2>/dev/null".format(TEST_HOME, "{}")
        self.app.settings.password_save_cmd = r"cat - > {}{}".format(TEST_HOME, "{}")
        parse_args(app=self.media_reader, args=["set-password", TestServerLogin.id, "username"])
        self.assertEquals(("username", "0"), self.app.settings.get_credentials(TestServerLogin.id))

    def test_print_app_state(self):
        self.add_arbitrary_media()
        chapter_id = list(self.media_reader.get_media_ids_in_library())[0]
        parse_args(app=self.media_reader, args=["list-chapters", chapter_id])
        parse_args(app=self.media_reader, args=["list"])
        parse_args(app=self.media_reader, args=["list-servers"])

    def test_print_settings_file(self):
        for f in ["settings_file", "metadata", "cookie_file"]:
            parse_args(app=self.media_reader, args=["get-file", f])

    def test_search_save(self):
        assert not len(self.media_reader.get_media_in_library())
        parse_args(app=self.media_reader, args=["--auto", "search", "manga"])
        assert len(self.media_reader.get_media_in_library())
        self.app.load_state()
        assert len(self.media_reader.get_media_in_library())

    def test_select(self):
        assert not len(self.media_reader.get_media_in_library())
        parse_args(app=self.media_reader, args=["--auto", "select", "manga"])
        assert not len(self.media_reader.get_media_in_library())

    def test_load(self):
        parse_args(app=self.media_reader, args=["--auto", "search", "InProgress"])
        assert len(self.media_reader.get_media_ids_in_library()) == 1
        media_data = next(iter(self.media_reader.get_media_in_library()))
        parse_args(app=self.media_reader, args=["--auto", "load", "--local-only", "test_user"])
        assert self.media_reader.get_tracker_info(media_data, self.media_reader.get_primary_tracker().id)
        self.assertEqual(media_data["progress"], self.media_reader.get_last_read(media_data))

    def test_load_add_new_media(self):
        parse_args(app=self.media_reader, args=["--auto", "load", "test_user"])
        assert len(self.media_reader.get_media_in_library()) > 1
        for media_data in self.media_reader.get_media_in_library():
            assert self.media_reader.get_tracker_info(media_data, self.media_reader.get_primary_tracker().id)
            if media_data["progress"]:
                self.assertEqual(media_data["progress"], self.media_reader.get_last_read(media_data))

    def test_copy_tracker(self):
        media_list = self.add_test_media()
        self.app.get_primary_tracker().set_custom_anime_list([media_list[0]["name"]], media_list[0]["media_type"])
        parse_args(app=self.media_reader, args=["--auto", "load", "test_user"])
        assert self.app.get_tracker_info(media_list[0])
        assert not self.app.get_tracker_info(media_list[1])
        parse_args(app=self.media_reader, args=["copy-tracker", media_list[0]["name"], media_list[1]["name"]])
        self.assertEquals(self.app.get_tracker_info(media_list[0]), self.app.get_tracker_info(media_list[1]))

    def test_share_tracker(self):
        media_list = self.add_test_media()
        parse_args(app=self.media_reader, args=["--auto", "load", "test_user"])
        tracked_media = [media_data["name"] for media_data in media_list if self.app.get_tracker_info(media_data)]
        parse_args(app=self.media_reader, args=["--auto", "share-tracker"])
        tracked_media2 = [media_data["name"] for media_data in media_list if self.app.get_tracker_info(media_data)]
        assert all([self.app.get_tracker_info(media_data) for media_data in media_list if media_data["name"] in tracked_media])
        assert len(tracked_media) < len(tracked_media2)

    def test_mark_up_to_date(self):
        media_list = self.add_test_media()
        media_data = media_list[0]
        name = self.app._get_global_id(media_data)
        parse_args(app=self.media_reader, args=["mark-up-to-date", name])
        assert all(map(lambda x: x["read"], media_data["chapters"].values()))
        parse_args(app=self.media_reader, args=["mark-up-to-date", "--force", name, "-1"])
        assert not all(map(lambda x: x["read"], media_data["chapters"].values()))
        parse_args(app=self.media_reader, args=["mark-up-to-date", "--abs", "--force", name, "-1"])
        assert not any(map(lambda x: x["read"], media_data["chapters"].values()))

    def test_sync_progress(self):
        parse_args(app=self.media_reader, args=["--auto", "load"])
        parse_args(app=self.media_reader, args=["mark-up-to-date"])
        parse_args(app=self.media_reader, args=["sync"])
        self.media_reader.media.clear()
        self.media_reader.load_state()
        for media_data in self.media_reader.get_media_in_library():
            self.assertEqual(self.media_reader.get_last_chapter_number(media_data), self.media_reader.get_last_read(media_data))
            self.assertEqual(media_data["progress"], self.media_reader.get_last_read(media_data))
        self.media_reader.media.clear()
        parse_args(app=self.media_reader, args=["--auto", "load"])
        for media_data in self.media_reader.get_media_in_library():
            self.assertEqual(self.media_reader.get_last_chapter_number(media_data), self.media_reader.get_last_read(media_data))
            self.assertEqual(media_data["progress"], self.media_reader.get_last_read(media_data))

    def test_download(self):
        media_list = self.add_test_media(no_update=True)
        assert len(media_list[0]["chapters"]) == 0
        parse_args(app=self.media_reader, args=["-u", "download-unread"])
        assert len(media_list[0]["chapters"])
        self.assertEqual(0, self.app.download_chapters(media_list[0]))

    def test_download_specific(self):
        media_list = self.add_test_media()
        media_data = media_list[0]
        chapters = self.app._get_sorted_chapters(media_data)
        parse_args(app=self.media_reader, args=["download", self.app._get_global_id(media_data), str(chapters[1]["number"]), str(chapters[-2]["number"])])
        for chapter_data in chapters[1:-2]:
            self.verify_download(media_data, chapter_data)

    def test_download_specific_single(self):
        media_list = self.add_test_media()
        media_data = media_list[0]
        chapters = self.app._get_sorted_chapters(media_data)
        parse_args(app=self.media_reader, args=["download", self.app._get_global_id(media_data), str(chapters[1]["number"])])
        self.verify_download(media_data, chapters[1])

        server = self.media_reader.get_server(media_data["server_id"])
        for chapter_data in chapters:
            if chapter_data != chapters[1]:
                assert not server.is_fully_downloaded(media_data, chapter_data)

    def test_download_next(self):
        self.add_test_media()
        for id, media_data in self.media_reader.media.items():
            server = self.app.get_server(media_data["server_id"])
            chapter = sorted(media_data["chapters"].values(), key=lambda x: x["number"])[0]
            parse_args(app=self.media_reader, args=["download-unread", "--limit", "1", id])
            self.assertEqual(0, server.download_chapter(media_data, chapter))

    def test_update(self):
        media_list = self.add_test_media(no_update=True)
        assert len(media_list[0]["chapters"]) == 0
        parse_args(app=self.media_reader, args=["update"])
        assert len(media_list[0]["chapters"])

    def test_update_replace(self):
        fake_chapter_id = "fakeId"
        media_list = self.add_test_media()
        self.app.mark_up_to_date()
        original_len = len(media_list[0]["chapters"])
        parse_args(app=self.media_reader, args=["update", "--replace"])
        assert fake_chapter_id not in media_list[0]["chapters"]
        assert original_len == len(media_list[0]["chapters"])
        self.assertAllChaptersRead(MANGA)

    def test_offset(self):
        media_list = self.add_test_media()
        media_data = media_list[0]
        chapters = media_data["chapters"]
        list_of_numbers = sorted([chapter_data["number"] for chapter_data in chapters.values()])
        offset_list = list(map(lambda x: x - 1, list_of_numbers))
        parse_args(app=self.media_reader, args=["offset", self.app._get_global_id(media_data), "1"])
        parse_args(app=self.media_reader, args=["update"])
        self.assertEqual(offset_list, sorted([chapter_data["number"] for chapter_data in chapters.values()]))
        self.verify_unique_numbers(media_data["chapters"])

    def test_search(self):
        assert not len(self.media_reader.get_media_in_library())
        parse_args(app=self.media_reader, args=["--auto", "search", "manga"])
        assert len(self.media_reader.get_media_in_library())
        self.assertRaises(ValueError, parse_args, app=self.media_reader, args=["--auto", "search", "manga"])

    def test_search_fail(self):
        parse_args(app=self.media_reader, args=["--auto", "search", "__UnknownMedia__"])

    def test_migrate(self):
        parse_args(app=self.media_reader, args=["--auto", "search", "manga"])
        parse_args(app=self.media_reader, args=["--auto", "load", "--local-only"])
        media_data = list(self.media_reader.get_media_in_library())[0]
        self.app.mark_up_to_date()

        assert self.media_reader.get_tracker_info(media_data)
        parse_args(app=self.media_reader, args=["--auto", "migrate", media_data["name"]])
        self.assertEqual(1, len(self.media_reader.get_media_in_library()))

        media_data2 = list(self.media_reader.get_media_in_library())[0]
        self.assertNotEqual(self.app._get_global_id(media_data), self.app._get_global_id(media_data2))
        self.assertEqual(self.app.get_last_read(media_data), self.app.get_last_read(media_data2))
        assert self.media_reader.get_tracker_info(media_data2)

    def test_migrate_self(self):
        parse_args(app=self.media_reader, args=["--auto", "search", "manga"])
        parse_args(app=self.media_reader, args=["--auto", "load", "--local-only"])
        media_data = list(self.media_reader.get_media_in_library())[0]

        self.app.mark_up_to_date()
        parse_args(app=self.media_reader, args=["migrate", "--self", media_data["name"]])
        self.assertEqual(1, len(self.media_reader.get_media_in_library()))

        media_data2 = list(self.media_reader.get_media_in_library())[0]
        self.assertEqual(self.app._get_global_id(media_data), self.app._get_global_id(media_data2))
        self.assertEqual(self.app.get_last_read(media_data), self.app.get_last_read(media_data2))
        assert self.media_reader.get_tracker_info(media_data2)

    def test_remove(self):
        parse_args(app=self.media_reader, args=["--auto", "search", "manga"])
        media_data = list(self.media_reader.get_media_in_library())[0]
        parse_args(app=self.media_reader, args=["remove", self.app._get_global_id(media_data)])
        self.assertEqual(0, len(self.media_reader.get_media_in_library()))

    def test_clean_bundle(self):
        self.add_test_media(self.test_server)
        parse_args(app=self.media_reader, args=["bundle"])
        parse_args(app=self.media_reader, args=["clean", "-b"])
        self.assertEqual(0, len(self.app.bundles))
        self.assertFalse(os.path.exists(self.settings.bundle_dir))

    def test_clean_removed(self):
        self.add_test_media(self.test_server)
        self.app.download_unread_chapters()
        self.app.media.clear()

        parse_args(app=self.media_reader, args=["clean"])
        for dir in os.listdir(self.settings.media_dir):
            self.assertEqual(0, len(os.listdir(os.path.join(self.settings.media_dir, dir))))

    def test_clean_read(self):
        self.add_test_media(self.test_server)
        self.app.download_unread_chapters()
        self.media_reader.mark_up_to_date()
        parse_args(app=self.media_reader, args=["clean", "--remove-read"])
        self.verifyNoChaptersDownloaded()

    def test_clean_servers(self):
        self.add_test_media(self.test_server)
        self.app.download_unread_chapters()
        self.app._servers.clear()
        parse_args(app=self.media_reader, args=["clean", "--remove-disabled-servers"])
        self.assertEqual(0, len(os.listdir(self.settings.media_dir)))

    def test_clean_unused(self):
        self.add_test_media(self.test_server)
        parse_args(app=self.media_reader, args=["clean", "--remove-not-on-disk"])
        self.assertEqual(0, len(os.listdir(self.settings.media_dir)))

    def test_view_chapter(self):
        media_list = self.add_test_media(self.test_server)
        media_data = media_list[0]
        parse_args(app=self.media_reader, args=["view", "--limit", "2", media_data["name"]])
        numRead = sum([chapter["read"] for chapter in media_data["chapters"].values()])
        self.assertEqual(2, numRead)

    def test_view_chapter_specific(self):
        media_list = self.add_test_media(self.test_server)
        media_data = media_list[0]
        parse_args(app=self.media_reader, args=["view", media_data["name"], "2"])
        for chapter in media_data["chapters"].values():
            self.assertEqual(chapter["number"] == 2, chapter["read"])
        self.assertEqual(1, sum([chapter["read"] for chapter in media_data["chapters"].values()]))

    def test_bundle_read(self):
        self.settings.manga_viewer = "[ -f {} ]"
        media_list = self.add_test_media(self.test_server)

        self.app.download_unread_chapters()
        parse_args(app=self.media_reader, args=["bundle"])
        assert len(self.app.bundles)
        name, bundle_data = list(self.app.bundles.items())[0]
        self.assertTrue(os.path.isabs(name))
        self.assertTrue(os.path.exists(name))
        self.assertEqual(len(bundle_data), sum([len(x["chapters"]) for x in media_list]))
        parse_args(app=self.media_reader, args=["read", os.path.basename(name)])
        self.assertAllChaptersRead(MANGA)

    def test_bundle_read_simple(self):
        self.settings.manga_viewer = "[ -f {} ]"
        self.add_test_media(self.test_server)
        parse_args(app=self.media_reader, args=["bundle"])
        parse_args(app=self.media_reader, args=["read"])
        self.assertAllChaptersRead(MANGA)

    def test_bundle_download_error(self):
        server = self.media_reader.get_server(TestServerLogin.id)
        self.add_test_media(server)
        server.fail_login = True
        self.assertRaises(ValueError, parse_args, app=self.media_reader, args=["bundle", TestServerLogin.id])
        assert not self.app.bundles

    def test_bundle_specific(self):
        media_list = self.add_test_media(self.test_server)
        self.app.download_unread_chapters()
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

    def test_bundle_limit(self):
        self.add_test_media(self.test_server)
        parse_args(app=self.media_reader, args=["bundle", "--limit=2"])
        bundle_data = list(self.media_reader.bundles.values())[0]
        self.assertEqual(len(bundle_data), 2)

    def test_play(self):
        self.add_test_media(self.test_anime_server)
        parse_args(app=self.media_reader, args=["play", "-c"])
        self.assertAllChaptersRead(ANIME)

    def test_play_fail(self):
        self.add_test_media(self.test_anime_server)

        self.settings.anime_viewer = "exit 1; #" + self.settings.anime_viewer
        parse_args(app=self.media_reader, args=["play", "-c"])
        assert not self.getNumChaptersRead(ANIME)

    def test_play_specific(self):
        media_list = self.add_test_media(self.test_anime_server)
        parse_args(app=self.media_reader, args=["play", "-c", media_list[0]["name"], "1", "3"])
        for chapter in self.app._get_sorted_chapters(media_list[0]):
            self.assertEquals(chapter["read"], chapter["number"] in [1, 3])

    def test_play_relative(self):
        media_list = self.add_test_media(self.test_anime_server)
        chapters = list(self.app._get_sorted_chapters(media_list[0]))
        chapters[1]["read"] = True
        parse_args(app=self.media_reader, args=["play", media_list[0]["name"], "-1"])
        assert chapters[0]["read"]

    def test_play_last_read(self):
        media_list = self.add_test_media(self.test_anime_server)
        chapters = list(self.app._get_sorted_chapters(media_list[0]))
        chapters[1]["read"] = True
        parse_args(app=self.media_reader, args=["play", media_list[0]["name"], "0"])
        self.assertEquals(1, self.getNumChaptersRead(ANIME))

    def test_get_stream_url(self):
        self.add_test_media(self.test_anime_server)
        parse_args(app=self.media_reader, args=["get-stream-url"])
        assert not self.getNumChaptersRead(ANIME)

    def test_stream(self):
        parse_args(app=self.media_reader, args=["stream", TestAnimeServer.stream_url])
        assert not len(self.media_reader.get_media_in_library())

    def test_stream_quality(self):
        parse_args(app=self.media_reader, args=["stream", "-q", "-1", TestAnimeServer.stream_url])

    def test_stream_download(self):
        parse_args(app=self.media_reader, args=["stream", "--download", TestAnimeServer.stream_url])
        assert not len(self.media_reader.get_media_in_library())
        server = self.app.get_server(TestAnimeServer.id)
        media_data = server.get_media_data_from_url(TestAnimeServer.stream_url)
        chapter_data = media_data["chapters"][server.get_chapter_id_for_url(TestAnimeServer.stream_url)]

        self.verify_download(media_data, chapter_data)

    def test_add_from_url_stream_cont(self):
        parse_args(app=self.media_reader, args=["add-from-url", TestAnimeServer.stream_url])
        assert len(self.media_reader.get_media_in_library()) == 1
        parse_args(app=self.media_reader, args=["stream", "--cont", TestAnimeServer.stream_url])
        self.assertAllChaptersRead(ANIME)

    def test_add_from_url_bad(self):
        self.assertRaises(ValueError, parse_args, app=self.media_reader, args=["add-from-url", "bad-url"])
        assert not self.media_reader.get_media_in_library()

    def test_import_auto_detect_name(self):
        samples = [
            ("ANIME", "Banner of the Stars", 1, "01. Banner of the Stars (Seikai no Senki) [480p][author].mkv"),
            ("ANIME", "Magical Girl Lyrical Nanoha", 13, "[author] Magical Girl Lyrical Nanoha - 13 (type) [deadbeef].mkv"),
            ("ANIME", "Magical Girl Lyrical Nanoha A's", 999, "[author] Magical Girl Lyrical Nanoha A's - 999.mkv"),
            ("ANIME", "Steins;Gate", 1, "01 - Steins;Gate.mkv"),
            ("ANIME", "Kaguya-sama", 1, "Kaguya-sama - 01.mkv"),
            ("ANIME", "ViVid Strike!", 1, "[First Name] ViVid Strike! - 01 [BD 1080p][247EFC8F].mkv"),
            ("ANIME", "Specials", 5.5, "[First Name] Specials - 05.5 [BD 1080p][247EFC8F].mkv"),
            ("ANIME", "Ending", 0, "[First Name] Ending - ED [BD 1080p][247EFC8F].mkv"),
            ("ANIME", "Attack No. 1", 2, "Attack No. 1 - 02.mkv"),
            ("ANIME", "Alien 9", 1, "[author] Alien 9 - OVA 01 [English Sub] [Dual-Audio] [480p].mkv"),
            ("MANGA", "shamanking0", 1, "shamanking0_vol1.pdf"),
            ("NOVEL", "i-refuse-to-be-your-enemy", 5, "i-refuse-to-be-your-enemy-volume-5.epub"),

        ]

        self.settings.anime_viewer = "[ -f {media} ] && echo {title}"
        for media_type, name, number, file_name in samples:
            with self.subTest(file_name=file_name):
                with open(file_name, "w") as f:
                    f.write("dummy_data")
                assert os.path.exists(file_name)
                parse_args(app=self.media_reader, args=["import", "--media-type", media_type, file_name])
                assert not os.path.exists(file_name)
                assert any([x["name"] == name for x in self.media_reader.get_media_in_library()])
                for media_data in self.media_reader.get_media_in_library():
                    if media_data["name"] == name:
                        chapters = list(media_data["chapters"].values())
                        self.assertEqual(len(chapters), 1)
                        self.assertEqual(chapters[0]["number"], number)
                        assert re.search(r"^\w+$", media_data["id"])
                        self.assertEqual(media_data["media_type"], MEDIA_TYPES[media_type])
                        if media_data["media_type"] == ANIME:
                            assert self.media_reader.play(name, any_unread=True)
                        else:
                            assert self.media_reader.view_chapters(name)

    def test_import_multiple(self):
        file_names = ["Media - 1.mp4", "MediaOther - 1.mp4", "Media - 2.mp4"]
        file_names2 = ["Media - 3.mp4", "MediaOther - 2.mp4", "Media - 4.mp4"]
        for name in file_names + file_names2:
            with open(name, "w") as f:
                f.write("dummy_data")
        for name_list in (file_names, file_names2):
            parse_args(app=self.media_reader, args=["import", "--media-type=ANIME"] + name_list)
            self.assertEqual(2, len(self.media_reader.get_media_in_library()))
            for name in name_list:
                with self.subTest(file_name=name):
                    assert any([x["name"] == name.split()[0] for x in self.media_reader.get_media_in_library()])

    def test_import(self):
        image = Image.new("RGB", (100, 100))
        path = os.path.join(TEST_HOME, "00-file.jpg")
        path2 = os.path.join(TEST_HOME, "test-dir")
        os.mkdir(path2)
        path_file = os.path.join(path2, "10.0 file3.jpg")
        path3 = os.path.join(TEST_HOME, "11.0 file4.jpg")
        image.save(path)
        image.save(path_file)
        image.save(path3)
        parse_args(app=self.media_reader, args=["import", "--link", path])
        self.assertEqual(1, len(self.media_reader.get_media_in_library()))
        assert os.path.exists(path)
        parse_args(app=self.media_reader, args=["import", "--name", "testMedia", path2])
        assert 2 == len(self.media_reader.get_media_in_library())
        assert any([x["name"] == "testMedia" for x in self.media_reader.get_media_in_library()])
        assert not os.path.exists(path2)

        for i, media_type in enumerate(MEDIA_TYPES.keys()):
            name = "name" + str(i)
            parse_args(app=self.media_reader, args=["import", "--link", "--name", name, "--media-type", media_type, path3])
            assert any([x["name"] == name for x in self.media_reader.get_media_in_library()])
            self.assertEqual(3 + i, len(self.media_reader.get_media_in_library()))
            assert os.path.exists(path3)

    def test_upgrade(self):
        media_list = self.add_test_media(self.test_anime_server)
        removed_key = "removed_key"
        media_list[0][removed_key] = False
        media_list[1].pop("media_type")
        next(iter(media_list[2]["chapters"].values())).pop("special")
        next(iter(media_list[3]["chapters"].values()))["old_chapter_field"] = 10
        parse_args(app=self.media_reader, args=["upgrade"])
        assert removed_key not in media_list[0]
        assert "media_type" in media_list[1]
        assert "special" in next(iter(media_list[2]["chapters"].values()))
        assert "old_chapter_field" not in next(iter(media_list[3]["chapters"].values()))

    def test_auto_upgrade_disabled_broken(self):
        media_list = self.add_test_media(self.test_anime_server)
        media_list[1].pop("media_type")

        def _upgrade_state():
            pass
        self.app.upgrade_state = _upgrade_state
        for b in (True, False):
            self.settings.auto_upgrade_state = b
            self.assertRaises(KeyError, parse_args, app=self.media_reader, args=["list"])
            assert "media_type" not in media_list[1]

    def test_auto_upgrade_seamless(self):
        self.settings.max_retires = 10
        media_list = self.add_test_media(self.test_anime_server)
        media_list[1].pop("media_type")
        assert self.app.save_state()
        parse_args(app=self.media_reader, args=["setting", "max_retires", "1"])
        self.assertEqual(self.settings.max_retires, 1)
        self.app.state.clear()
        self.app.load_state()
        for media_data in self.app.get_media_in_library():
            assert "media_type" in media_data


class ServerTest(RealBaseUnitTestClass):
    def setUp(self):
        super().setUp()

    def test_get_media_list(self):
        for server in self.media_reader.get_servers():
            media_list = None
            with self.subTest(server=server.id, method="get_media_list"):
                media_list = server.search("One Piece")
                if not media_list:
                    media_list = server.search("Attack")
                if not media_list:
                    self.skipTest("Can't load media")
                assert media_list
                assert isinstance(media_list, list)
                assert all([isinstance(x, dict) for x in media_list])
                assert all([x["media_type"] == server.media_type for x in media_list])
            if not media_list:
                continue
            with self.subTest(server=server.id, method="search"):
                search_media_list = server.search(media_list[0]["name"])
                assert isinstance(search_media_list, list)
                assert all([isinstance(x, dict) for x in search_media_list])

            for i in (0, -1):
                with self.subTest(server=server.id, method="update_media_data", i=i):
                    media_data = media_list[i]
                    return_val = server.update_media_data(media_data)
                    assert not return_val
                    assert isinstance(media_data["chapters"], dict)

    def test_media_download_stream(self, stream=False):
        for server in self.media_reader.get_servers():
            with self.subTest(server=server.id):
                media_list = server.get_media_list()
                if not media_list:
                    self.skipTest("Can't load media")
                media_data = server.get_media_list()[0]
                self.app.add_media(media_data)
                for chapter_data in filter(lambda x: not x["premium"], media_data["chapters"].values()):
                    with self.subTest(server=server.id, stream=True):
                        if media_data["media_type"] & ANIME:
                            assert self.app.play(self.app._get_global_id(media_data), num_list=[chapter_data["number"]])
                    with self.subTest(server=server.id, stream=False):
                        unittest.skipIf(os.getenv("SKIP_DOWNLOAD"), "Download tests is not enabled")
                        assert not server.external == server.download_chapter(media_data, chapter_data, page_limit=2)
                        self.verify_download(media_data, chapter_data)
                        assert not server.download_chapter(media_data, chapter_data, page_limit=1)
                    break

    def test_login_fail(self):
        for server in self.media_reader.get_servers():
            if not server.has_login:
                continue

            with self.subTest(server=server.id, method="login"):
                try:
                    assert not server.login("A", "B")
                except:
                    pass

            server.settings.password_manager_enabled = False
            with self.subTest(server=server.id, method="relogin"):
                assert not server.relogin()

            server.settings.password_manager_enabled = True
            server.settings.password_load_cmd = r"echo -e A\\tB"
            with self.subTest(server=server.id, method="relogin"):
                assert not server.relogin()

    def test_search_media(self):
        interesting_media = ["Gintama", "One Piece"]
        for media in interesting_media:
            with self.subTest(media_name=media):
                self.media_reader.media.clear()
                media_data = self.media_reader.search_for_media(media)
                self.assertTrueOrSkipTest(media)
                for data in media_data:
                    self.media_reader.add_media(data)
                    self.verify_unique_numbers(data["chapters"])
                self.assertEqual(len(self.media_reader.get_media_in_library()), len(media_data))


class ServerStreamTest(RealBaseUnitTestClass):
    streamable_urls = [
        ("https://j-novel.club/read/i-refuse-to-be-your-enemy-volume-1-part-1", "i-refuse-to-be-your-enemy", None, "i-refuse-to-be-your-enemy-volume-1-part-1"),
        ("https://mangaplus.shueisha.co.jp/viewer/1000486", "100020", None, "1000486"),
        ("https://vrv.co/watch/GR3VWXP96/One-Piece:Im-Luffy-The-Man-Whos-Gonna-Be-King-of-the-Pirates", "GRMG8ZQZR", "GYVNM8476", "GR3VWXP96"),
        ("https://www.crunchyroll.com/manga/to-your-eternity/read/1", "499", None, "16329"),
        ("https://www.crunchyroll.com/one-piece/episode-1-im-luffy-the-man-whos-gonna-be-king-of-the-pirates-650673", "257631", "21685", "650673"),
        ("https://www.crunchyroll.com/rezero-starting-life-in-another-world-/episode-31-the-maidens-gospel-796209", "269787", "25186", "796209"),
        ("https://www.crunchyroll.com/the-irregular-at-magic-high-school/episode-1-enrollment-part-i-652193", "260315", "21563", "652193"),
        ("https://www.funimation.com/en/shows/one-piece/im-luffy-the-man-whos-gonna-be-king-of-the-pirates/?lang=japanese", "20224", "20227", "22333"),
        ("https://www.viz.com/shonenjump/one-piece-chapter-1/chapter/5090?action=read", "one-piece", None, "5090")
    ]

    premium_streamable_urls = [
        ("https://www.funimation.com/shows/bofuri-i-dont-want-to-get-hurt-so-ill-max-out-my-defense/defense-and-first-battle/?lang=japanese", "1019573", "1019574", "1019900"),
        ("https://www.funimation.com/shows/the-irregular-at-magic-high-school/visitor-arc-i/simulcast/?lang=japanese&qid=f290b76b82d5938b", "1079937", "1174339", "1174543"),
    ]

    def test_media_add_from_url(self):
        for url, media_id, season_id, chapter_id in self.streamable_urls:
            with self.subTest(url=url):
                servers = list(filter(lambda server: server.can_stream_url(url), self.media_reader.get_servers()))
                self.assertTrueOrSkipTest(servers)
                for server in servers:
                    with self.subTest(url=url, server=server.id):
                        media_data = server.get_media_data_from_url(url)
                        assert media_data
                        server.update_media_data(media_data)
                        self.assertEqual(media_id, str(media_data["id"]))
                        self.assertTrue(chapter_id in media_data["chapters"])
                        self.assertEqual(chapter_id, str(server.get_chapter_id_for_url(url)))
                        if season_id:
                            self.assertEqual(season_id, str(media_data["season_id"]))

                        _, chapter_data = self.app.get_media_by_chapter_id(server.id, server.get_chapter_id_for_url(url), [media_data])
                        self.assertEqual(str(chapter_data["id"]), str(chapter_id))
                        self.assertTrue(chapter_id in media_data["chapters"])
                        assert self.app.add_from_url(url)

    def test_media_steam(self):
        url_list = self.streamable_urls if not os.getenv("PREMIUM_TEST") else self.streamable_urls + self.premium_streamable_urls
        for url, media_id, season_id, chapter_id in url_list:
            for url, media_id, season_id, chapter_id in self.streamable_urls:
                with self.subTest(url=url):
                    servers = list(filter(lambda server: server.can_stream_url(url), self.media_reader.get_servers()))
                    self.assertTrueOrSkipTest(servers)
                    for server in servers:
                        if server.media_type == ANIME:
                            assert self.app.stream(url)


class ServerSpecificTest(RealBaseUnitTestClass):
    def test_crunchyroll_session(self):
        from ..servers.crunchyroll import Crunchyroll
        server = self.media_reader.get_server(Crunchyroll.id)
        self.assertTrueOrSkipTest(server)
        server = self.media_reader.get_server(Crunchyroll.id)
        bad_session = "bad_session"
        server.session.cookies["session_id"] = bad_session
        session = server.get_session_id()
        assert bad_session != session
        assert session == server.get_session_id()
        assert not server.api_auth_token
        assert server.needs_authentication()
        assert not server.api_auth_token


@unittest.skipUnless(os.getenv("PREMIUM_TEST"), "Premium tests is not enabled")
class PremiumTest(RealBaseUnitTestClass):
    def setUp(self):
        super().setUp()
        self.settings.password_manager_enabled = True

    @unittest.skipIf(os.getenv("SKIP_DOWNLOAD"), "Download tests is not enabled")
    def test_download_premium(self):
        for server in self.media_reader.get_servers():
            if server.has_login and not isinstance(server, TestServer):
                with self.subTest(server=server.id, method="get_media_list"):
                    media_list = server.get_media_list()
                    download_passed = False
                    for media_data in media_list:
                        server.update_media_data(media_data)
                        chapter_data = next(filter(lambda x: x["premium"], media_data["chapters"].values()), None)
                        if chapter_data:
                            assert server.download_chapter(media_data, chapter_data, page_limit=1)
                            assert not server.download_chapter(media_data, chapter_data, page_limit=1)

                            self.verify_download(media_data, chapter_data)
                            download_passed = True
                            break
                    assert download_passed

    def test_get_list(self):
        for tracker in self.media_reader.get_trackers():
            with self.subTest(tracker=tracker.id):
                data = tracker.get_tracker_list(id=1)
                assert data
                assert isinstance(data, list)
                assert isinstance(data[0], dict)

    def test_test_login(self):
        assert self.app.test_login()
        for server in self.media_reader.get_servers():
            if server.has_login:
                with self.subTest(server=server.id):
                    assert not server.needs_authentication()


class TrackerTest(RealBaseUnitTestClass):

    def test_num_trackers(self):
        assert self.media_reader.get_primary_tracker()
        assert self.media_reader.get_secondary_trackers()

    def test_get_list(self):
        for tracker in self.media_reader.get_trackers():
            with self.subTest(tracker=tracker.id):
                data = tracker.get_tracker_list(id=1)
                assert data
                assert isinstance(data, list)
                assert isinstance(data[0], dict)

    def test_no_auth(self):
        self.settings.password_manager_enabled = False
        for tracker in self.media_reader.get_trackers():
            if tracker.id != TestTracker.id:
                with self.subTest(tracker=tracker.id):
                    try:
                        tracker.update([])
                        assert False
                    except ValueError:
                        pass


def load_tests(loader, tests, pattern):

    clazzes = inspect.getmembers(sys.modules[__name__], inspect.isclass)
    test_cases = [c for _, c in clazzes if issubclass(c, BaseUnitTestClass)]
    test_cases.sort(key=lambda f: findsource(f)[1])
    suite = unittest.TestSuite()
    for test_class in test_cases:
        tests = loader.loadTestsFromTestCase(test_class)
        suite.addTests(tests)
    return suite
