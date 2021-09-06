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
from ..args import parse_args
from ..job import Job, RetryException
from ..media_reader import SERVERS, TRACKERS, import_sub_classes
from ..media_reader_cli import MediaReaderCLI
from ..servers.custom import CustomServer, get_local_server_id
from ..settings import Settings
from ..state import State
from ..util.decoder import GenericDecoder
from ..util.media_type import MediaType
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


class TestApplication(MediaReaderCLI):
    def __init__(self, real=False, local=False):
        settings = Settings(home=TEST_HOME)
        if os.path.exists(settings.get_cookie_file()):
            os.remove(settings.get_cookie_file())

        _servers = list(TEST_SERVERS)
        _trackers = list(TEST_TRACKERS)
        if real:
            if os.getenv("ENABLE_ONLY_SERVERS"):
                enabled_servers = set(os.getenv("ENABLE_ONLY_SERVERS").split(","))
                _servers = [x for x in SERVERS if x.id in enabled_servers]
                assert _servers
            else:
                _servers = [s for s in SERVERS if not s.external]
            _trackers += TRACKERS
        elif local:
            _servers += LOCAL_SERVERS

        _servers.sort(key=lambda x: x.id)
        super().__init__(_servers, _trackers, settings)
        if not settings.allow_only_official_servers:
            assert len(self.get_servers()) == len(_servers)
        assert len(self.get_trackers()) == len(_trackers)
        assert len(self.get_trackers()) == 1 + len(self.get_secondary_trackers())

    def save(self):
        self.state.save()


class BaseUnitTestClass(unittest.TestCase):
    real = False
    local = False

    def __init__(self, methodName="runTest"):
        super().__init__(methodName=methodName)
        self.init()

    def init(self):
        pass

    def reload(self):
        self.media_reader = TestApplication(self.real, self.local)

    def for_each(self, func, media_list, raiseException=True):
        Job(self.settings.threads if not os.getenv("DEBUG") else 0, [lambda x=media_data: func(x) for media_data in media_list], raiseException=raiseException).run()

    def setup_settings(self):
        self.media_reader.settings.password_override_prefix = None
        self.media_reader.settings.free_only = True
        self.media_reader.settings.no_save_session = True
        self.media_reader.settings.no_load_session = True
        self.media_reader.settings.password_manager_enabled = True
        self.media_reader.settings.password_load_cmd = r"echo -e a\\tb"
        self.media_reader.settings.shell = True
        if not self.real:
            self.media_reader.settings.threads = 0
        else:
            self.media_reader.settings.threads = max(8, len(self.media_reader.get_servers()))

        self.media_reader.settings.suppress_cmd_output = True
        self.media_reader.settings.viewer = "echo {media} {title}"
        self.media_reader.settings.specific_settings = {}
        self.media_reader.settings.bundle_viewer = "[ -f {media} ]"
        self.media_reader.settings.bundle_cmds[self.media_reader.settings.bundle_format] = "ls {files}; touch {name}"

        self.assertFalse(self.media_reader.settings.skip_ssl_verification())

    def setUp(self):
        self.stream_handler = logging.StreamHandler(sys.stdout)
        logger = logging.getLogger()
        logger.handlers = []
        logger.addHandler(self.stream_handler)
        shutil.rmtree(TEST_HOME, ignore_errors=True)
        self.reload()
        self.setup_settings()
        self.settings = self.media_reader.settings
        self.test_server = self.media_reader.get_server(TestServer.id)
        self.test_anime_server = self.media_reader.get_server(TestAnimeServer.id)
        assert not self.media_reader.get_media_ids()

    def tearDown(self):
        shutil.rmtree(TEST_HOME, ignore_errors=True)
        self.media_reader.session.close()
        for server in self.media_reader.get_servers():
            if server.session != self.media_reader.session:
                server.session.close()
        logging.getLogger().removeHandler(self.stream_handler)

    def add_test_media(self, server=None, no_update=False, limit=None):
        media_list = server.get_media_list() if server else [x for server in self.media_reader.get_servers() for x in server.get_media_list()]
        for media_data in media_list[:limit]:
            self.media_reader.add_media(media_data, no_update=no_update)
        assert media_list
        return media_list

    def getChapters(self, media_type=MediaType.ANIME | MediaType.MANGA):
        return [x for media_data in self.media_reader.get_media(media_type=media_type) for x in media_data["chapters"].values()]

    def verify_all_chapters_read(self, media_type=None):
        assert all(map(lambda x: x["read"], self.getChapters(media_type)))

    def get_num_chapters_read(self, media_type=None):
        return sum(map(lambda x: x["read"], self.getChapters(media_type)))

    def verify_download(self, media_data, chapter_data, skip_file_type_validation=False):
        server = self.media_reader.get_server(media_data["server_id"])
        if server.external:
            return
        valid_image_formats = ("png", "jpeg", "jpg")
        assert server.is_fully_downloaded(media_data, chapter_data)

        dir_path = server._get_dir(media_data, chapter_data)
        for dirpath, dirnames, filenames in os.walk(dir_path):
            for file_name in filenames:
                assert len(filenames) > 1, f"files: {filenames}, dirnames: {dirnames}"
                if not file_name.startswith("."):
                    path = os.path.join(dir_path, dirpath, file_name)
                    assert os.path.exists(path)
                    if skip_file_type_validation:
                        continue
                    media_type = MediaType(media_data["media_type"])
                    if media_type == MediaType.MANGA:
                        with open(path, "rb") as img_file:
                            img = Image.open(img_file)
                            self.assertIn(img.format.lower(), valid_image_formats)
                            self.assertIn(file_name.split(".")[-1], valid_image_formats)
                    elif media_type == MediaType.ANIME:
                        if path.endswith(server.extension):
                            subprocess.check_call(["ffprobe", "-loglevel", "quiet", path])

    def get_all_chapters(self):
        for media_data in self.media_reader.get_media():
            server = self.media_reader.get_server(media_data["server_id"])
            for chapter in media_data.get_sorted_chapters():
                yield server, media_data, chapter

    def verify_all_chapters_downloaded(self):
        for server, media_data, chapter in self.get_all_chapters():
            self.assertTrue(server.is_fully_downloaded(media_data, chapter))

    def verify_no_chapters_downloaded(self):
        for server, media_data, chapter in self.get_all_chapters():
            self.assertFalse(server.is_fully_downloaded(media_data, chapter))

    def verify_unique_numbers(self, chapters):
        list_of_numbers = sorted([chapter_data["number"] for chapter_data in chapters.values() if not chapter_data["special"]])
        set_of_numbers = sorted(list(set(list_of_numbers)))
        self.assertEqual(set_of_numbers, list_of_numbers)
        return set_of_numbers

    def verify_no_media(self):
        assert not self.media_reader.get_media_ids()

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


class UtilTest(BaseUnitTestClass):
    def test(self):
        for media_type in list(MediaType):
            self.assertEqual(media_type, MediaType.get(media_type.name))
        self.assertEqual(MediaType.MANGA, MediaType.get("bad_name", MediaType.MANGA))


class DecoderTest(BaseUnitTestClass):
    simple_img = [
        [1, 1, 1, 1, 2, 2, 0, 0],
        [1, 1, 1, 1, 2, 2, 0, 0],
        [1, 1, 1, 1, 2, 2, 2, 9],

        [1, 1, 1, 1, 2, 2, 2, 9],
        [3, 3, 3, 3, 4, 4, 2, 9],
        [3, 3, 3, 3, 4, 4, 4, 9],

        [0, 0, 3, 3, 3, 4, 4, 9],
        [0, 0, 9, 9, 9, 9, 9, 9]
    ], (3, 3), ((0, 1), (2, 3))
    scrambled_img = [
        [1, 2, 2, 1, 2, 2, 0, 0],
        [1, 2, 2, 3, 4, 4, 0, 0],
        [1, 2, 2, 3, 4, 4, 2, 9],

        [1, 1, 1, 1, 1, 1, 2, 9],
        [3, 3, 3, 1, 1, 1, 2, 9],
        [3, 3, 3, 1, 1, 1, 2, 9],

        [0, 0, 3, 3, 3, 4, 4, 9],
        [0, 0, 9, 9, 9, 9, 9, 9]
    ], (3, 3), ((3, 0), (2, 1))
    descrambled = [
        [1, 1, 1, 2, 2, 9],
        [1, 1, 1, 2, 2, 9],
        [1, 1, 1, 2, 2, 9],

        [3, 3, 3, 4, 4, 9],
        [3, 3, 3, 4, 4, 9],
        [9, 9, 9, 9, 9, 9],
    ]

    def assert_img_eq(self, img1, img2):
        self.assertEqual(img1.size, img2.size)
        pixels1, pixels2 = img1.load(), img2.load()
        for y in range(img1.height):
            for x in range(img1.width):
                self.assertEqual(pixels1[x, y], pixels2[x, y])

    def create_img_from_array(self, array):
        img = Image.new("I", (len(array[0]), len(array)))
        img.putdata([col for row in array for col in row])
        self.assertEqual(img.size, (len(array[0]), len(array)))
        return img

    def do_image_decoding(self, source_arr, dims, solution_grid, correct_img):
        img = self.create_img_from_array(source_arr)
        final_img, sorted_cells = GenericDecoder.solve_image_helper(img, W=dims[0], H=dims[1], offset=(1, 1))
        self.assertTrue(final_img)
        self.assert_img_eq(final_img, self.create_img_from_array(correct_img))
        self.assertEqual(GenericDecoder.cells_to_int_matrix(sorted_cells), solution_grid)

    def test_image_decoding_simple(self):
        self.do_image_decoding(self.simple_img[0], self.simple_img[1], self.simple_img[2], self.descrambled)

    def test_image_decoding_scrambled(self):
        self.do_image_decoding(self.scrambled_img[0], self.scrambled_img[1], self.scrambled_img[2], self.descrambled)

    def test_solve_image_degenerate(self):
        img = Image.new("RGB", (512, 256))
        final_img = GenericDecoder.solve_image(img)
        self.assertTrue(final_img)
        self.assert_img_eq(final_img, Image.new("RGB", final_img.size))

    def test_solve_image_exp_reduction(self):
        # grid with "2" being an incorrect value
        array = [
                [1, 1, 1, 1, 0, 0, 0, 0],
                [1, 1, 1, 1, 0, 0, 0, 0],
                [1, 1, 1, 1, 0, 2, 0, 0],
        ]
        # bunch of identical squares
        array.extend([[0] * len(array[0])] * 11)
        img = self.create_img_from_array(array)
        final_img = GenericDecoder.solve_image_helper(img, W=3, H=3, offset=(1, 1))[0]
        self.assertTrue(final_img)

    def test_abort_solve_image(self):
        img = Image.new("RGB", (1080, 720))
        final_img = GenericDecoder.solve_image(img, max_iters=1)
        self.assertFalse(final_img)

    def test_solve_image_cache(self):
        img = Image.new("RGB", (1080, 720))
        key = "Key"
        for i in range(100):
            self.assertTrue(GenericDecoder.solve_image(img, key=key))


class SettingsTest(BaseUnitTestClass):

    separators = ("\t", "\n", "\r", "some_string")

    def setUp(self):
        super().setUp()
        self.settings.password_manager_enabled = True
        self.settings.password_load_cmd = "cat {}{} 2>/dev/null".format(TEST_HOME, "{}")
        self.settings.password_save_cmd = r"cat - > {}{}".format(TEST_HOME, "{}")

    def test_settings_save_load(self):
        self.settings.password_save_cmd = "dummy_cmd"
        self.settings.save(save_all=True)

        assert Settings(home=TEST_HOME).password_save_cmd == "dummy_cmd"

    def test_settings_env_override(self):
        os.environ["AMT_PASSWORD_LOAD_CMD"] = "1"
        self.settings.load()
        self.assertEqual(self.settings.password_load_cmd, "1")
        del os.environ["AMT_PASSWORD_LOAD_CMD"]

    @patch("builtins.input", return_value="0")
    @patch("getpass.getpass", return_value="1")
    def test_settings_env_override_ask_credentials(self, _username, _password):
        os.environ["AMT_QUICK_TRY"] = "1"
        self.settings.load()
        self.assertEquals(("0", "1"), self.media_reader.settings.get_credentials(TestServerLogin.id))
        del os.environ["AMT_QUICK_TRY"]

    def test_credentials(self):
        server_id = "test"
        assert not self.settings.get_credentials(server_id)
        username, password = "user", "pass"
        self.settings.store_credentials(server_id, username, password)
        self.assertEqual((username, password), self.settings.get_credentials(server_id))
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
        self.settings.password_override_prefix = "prefix"
        server_id = "test"
        username, password = "user", "pass"
        for sep in self.separators:
            self.settings.credential_separator = sep
            with self.subTest(sep=sep):
                os.environ[self.settings.password_override_prefix + server_id] = f"{username}{sep}{password}"
                try:
                    self.assertEqual(username, self.settings.get_credentials(server_id)[0])
                    self.assertEqual(password, self.settings.get_credentials(server_id)[1])
                    assert not self.settings.get_credentials("bad_id")
                finally:
                    del os.environ[self.settings.password_override_prefix + server_id]

    def test_is_allowed_text_lang(self):
        assert self.settings.is_allowed_text_lang("en", TestServer.id)

    def test_bundle(self):
        name = self.settings.bundle("")
        assert name.endswith("." + self.settings.bundle_format)
        self.assertTrue(os.path.exists(name))
        assert self.settings.open_bundle_viewer(name)
        self.settings.bundle_viewer = "exit 1"
        assert not self.settings.open_bundle_viewer(name)

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
            self.assertEqual(media_data.get_sorted_chapters(), list(map(lambda x: x[1], sorted_paths)))

    def test_auto_replace(self):
        self.settings.auto_replace = True
        with open(self.settings.get_replacement_file(), 'w') as f:
            f.write("s/Big Sister/Onee-san/g\n")
            f.write("Big Brother ([A-Z]\w*)/\\1 onii-san\n")

        text = "Big Sister where is Big Brother X"
        target = "Onee-san where is X onii-san"
        self.assertEqual(self.settings.auto_replace_if_enabled(text), target)

    def test_auto_replace_file_does_not_exist(self):
        self.settings.auto_replace = True
        text = "Big Sister where is Big Brother X"
        self.assertEqual(self.settings.auto_replace_if_enabled(text), text)

    def test_auto_replace_dir(self):
        media_data = self.add_test_media(server=self.test_server, limit=1)[0]
        self.settings.auto_replace = True
        os.mkdir(self.settings.get_replacement_dir())
        path = os.path.join(self.settings.get_replacement_dir(), TestServer.id)
        with open(path, 'w') as f:
            f.write("s/A/B/g\n")
        with open(self.settings.get_replacement_file(), 'w') as f:
            f.write("s/B/C/g\n")
        text = "A A"
        target = "B B"
        self.assertEqual(self.settings.auto_replace_if_enabled(text), text)
        self.assertEqual(self.settings.auto_replace_if_enabled(text, media_data), target)


class ServerWorkflowsTest(BaseUnitTestClass):

    def setUp(self):
        super().setUp()
        self.media_reader.settings.password_manager_enabled = True

    def test_skip_servers_that_cannot_be_imported(self):
        with patch.dict(sys.modules, {"amt.tests.test_server": None}):
            remaining_servers = set()
            import_sub_classes(tests, TestServer, remaining_servers)
            self.assertNotEqual(remaining_servers, TEST_SERVERS)

    def test_media_reader_add_remove_media(self):
        for server in self.media_reader.get_servers():
            with self.subTest(server=server.id):
                media_list = server.get_media_list()
                assert media_list
                selected_media = media_list[0]
                self.media_reader.add_media(selected_media)
                my_media_id_list = list(self.media_reader.get_media_ids())
                self.assertEqual(1, len(my_media_id_list))
                self.assertEqual(my_media_id_list[0], selected_media.global_id)
                self.media_reader.remove_media(media_data=selected_media)
                self.verify_no_media()

    def test_server_download(self):
        for server in self.media_reader.get_servers():
            for media_data in server.get_media_list():
                with self.subTest(server=server.id, media_data=media_data["name"]):
                    server.update_media_data(media_data)
                    chapter_data = list(media_data["chapters"].values())[0]
                    self.assertEqual(True, server.download_chapter(media_data, chapter_data, page_limit=2))
                    self.verify_download(media_data, chapter_data)

    def test_server_download_errors(self):
        media_data = self.add_test_media(server=self.test_server, limit=1)[0]
        self.test_server.inject_error(delay=1)
        self.assertRaises(Exception, self.media_reader.download_unread_chapters, media_data)
        self.media_reader.download_unread_chapters(media_data)
        self.verify_all_chapters_downloaded()

    def test_search_media(self):
        for server in self.media_reader.get_servers():
            with self.subTest(server=server.id):
                media_data = server.get_media_list()[0]
                name = media_data["name"]
                assert media_data == list(server.search(name))[0]
                assert server.search(name[:3])

    def login_test_helper(self):
        server = self.media_reader.get_server(TestServerLogin.id)
        self.add_test_media(server=server)
        self.assertRaises(ValueError, self.media_reader.download_unread_chapters)

    def test_login_non_premium_account(self):
        self.media_reader.get_server(TestServerLogin.id).premium_account = False
        self.login_test_helper()

    def test_login_no_credentials(self):
        self.settings.password_manager_enabled = False
        self.login_test_helper()

    def test_error_on_login(self):
        self.media_reader.get_server(TestServerLogin.id).error_login = True
        self.login_test_helper()

    def test_server_download_inaccessiable(self):
        self.media_reader.get_server(TestServerLogin.id).inaccessible = True
        self.login_test_helper()


class MediaReaderTest(BaseUnitTestClass):
    def test_disable_unofficial_servers(self):
        self.add_test_media()

        for i in range(2):
            self.assertFalse(all(map(lambda x: self.media_reader.get_server(x["server_id"]).official, self.media_reader.get_media())))
            self.media_reader.save()
            self.media_reader.settings.allow_only_official_servers = True
            self.media_reader.settings.save(save_all=True)
            self.reload()
            self.assertTrue(self.media_reader.settings.allow_only_official_servers)
            self.assertTrue(self.media_reader.get_media_ids())
            self.assertTrue(all(map(lambda x: self.media_reader.get_server(x["server_id"]).official, self.media_reader.get_media())))
            self.media_reader.settings.allow_only_official_servers = False
            self.media_reader.settings.save()
            self.reload()

    def test_load_cookies_session_cookies(self):
        self.media_reader.settings.no_load_session = False
        name, value = "Test", "value"
        name2, value2 = "Test2", "value2"
        self.settings.cookie_files = []
        with open(self.settings.get_cookie_file(), "w") as f:
            f.write("\t".join([TestServer.domain, "TRUE", "/", "FALSE", "1640849596", name, value, "None"]))
            f.write("\n#Comment\n")
            f.write("\t".join([f"#HttpOnly_.{TestServer.domain}", "TRUE", "/", "FALSE", "1640849596", name2, value2, "None"]))

        self.media_reader.state.load_session_cookies()
        assert self.media_reader.session.cookies
        self.assertEqual(value, self.media_reader.session.cookies.get(name))
        self.assertEqual(value2, self.media_reader.session.cookies.get(name2))

    def test_save_load_cookies(self):
        self.media_reader.settings.no_load_session = False
        self.media_reader.settings.no_save_session = False
        key, value = "Test", "value"
        self.test_server.add_cookie(key, value)
        assert self.media_reader.state.save_session_cookies()
        self.test_server.add_cookie(key, "bad_value")
        self.media_reader.state.load_session_cookies()
        self.assertEqual(value, self.media_reader.session.cookies.get(key))
        self.test_server.add_cookie(key, "bad_value")
        self.media_reader.state.load_session_cookies()
        assert not self.media_reader.state.save_session_cookies()

    def test_save_load(self):
        assert not os.path.exists(self.settings.get_metadata())
        self.add_test_media(server=self.test_server)
        old_hash = State.get_hash(self.media_reader.media)
        self.media_reader.save()
        assert os.path.exists(self.settings.get_metadata())
        self.reload()
        self.assertEqual(old_hash, State.get_hash(self.media_reader.media))
        for media_data in self.media_reader.get_media():
            self.assertTrue(media_data["chapters"])
            self.assertTrue(media_data.chapters)

    def test_save_load_global_id_format_change(self):
        self.add_test_media(server=self.test_server)
        original_keys = set(self.media_reader.media.keys())
        for key in original_keys:
            self.media_reader.media["old_" + key] = self.media_reader.media[key]
            del self.media_reader.media[key]
        self.media_reader.save()
        self.reload()
        self.assertEqual(original_keys, set(self.media_reader.media.keys()))

    def test_save_load_disabled(self):
        self.add_test_media()
        old_hash = State.get_hash(self.media_reader.media)
        self.media_reader.save()
        self.media_reader.state.configure_media({})
        assert not self.media_reader.media
        self.media_reader.save()
        self.media_reader.state.configure_media(self.media_reader.get_servers_ids())
        assert self.media_reader.media
        self.assertEqual(old_hash, State.get_hash(self.media_reader.media))

    def test_mark_chapters_until_n_as_read(self):
        media_data = self.add_test_media(server=self.test_server, limit=1)[0]
        assert len(media_data["chapters"]) > 2
        last_chapter_num = max(media_data["chapters"].values(), key=lambda x: x["number"])["number"]
        last_chapter_num_read = last_chapter_num - 1
        assert last_chapter_num > 1
        self.media_reader.mark_chapters_until_n_as_read(media_data, last_chapter_num_read)

        assert all(map(lambda x: x["read"], filter(lambda x: last_chapter_num_read >= x["number"], media_data["chapters"].values())))

    def test_download_unread_chapters(self):
        media_list = self.add_test_media(self.test_server)
        count = self.media_reader.download_unread_chapters()

        self.assertEqual(count, sum([len(media_data["chapters"]) for media_data in media_list]))

        for media_data in media_list:
            for chapter_data in media_data["chapters"].values():
                self.verify_download(media_data, chapter_data, skip_file_type_validation=True)

    def test_update_no_media(self):
        assert not self.media_reader.update()

    def test_update(self):
        self.media_reader.settings.free_only = False
        media_data = self.add_test_media(server=self.test_server, limit=1, no_update=True)[0]
        num_new_chapters = self.media_reader.update_media(media_data)
        self.assertTrue(num_new_chapters)
        self.assertFalse(self.media_reader.update_media(media_data))
        media_data["chapters"].clear()
        num_new_chapters2 = self.media_reader.update_media(media_data)
        self.assertEqual(num_new_chapters, num_new_chapters2)

    def test_update_replace_error(self):
        self.add_test_media(server=self.test_server, limit=1)
        self.media_reader.mark_read()
        self.test_server.inject_error()
        self.media_reader.update(replace=True, ignore_errors=True)
        self.verify_all_chapters_read()

    def test_update_hidden_media(self):
        media_list = self.add_test_media(server=self.test_server)
        self.test_server.hide = True
        numMedia = len(media_list)
        initialChapters = len(self.getChapters())
        assert not self.media_reader.update()
        self.assertEquals(numMedia, len(self.media_reader.get_media_ids()))
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
        self.media_reader.mark_read()
        for i in range(2):
            for media_data in media_list:
                assert all(map(lambda x: x["read"], media_data["chapters"].values()))
            self.media_reader.update()

    def test_mark_read(self):
        media_list = self.add_test_media(self.test_server)
        self.media_reader.mark_read(self.test_server.id)
        for media_data in media_list:
            assert all(map(lambda x: x["read"], media_data["chapters"].values()))
        self.media_reader.mark_read(self.test_server.id, N=-1)
        for media_data in media_list:
            assert all(map(lambda x: x["read"], media_data["chapters"].values()))
        self.media_reader.mark_read(self.test_server.id, N=-1, force=True)
        for media_data in media_list:
            chapter_list = media_data.get_sorted_chapters()
            assert all(map(lambda x: x["read"], chapter_list[:-1]))
            assert not chapter_list[-1]["read"]

    def _prepare_for_bundle(self, id=TestServer.id, no_download=False):
        server = self.media_reader.get_server(id)
        media_list = self.add_test_media(server=server, limit=2)
        num_chapters = 0
        for media_data in media_list:
            num_chapters += len(media_data["chapters"])

        if not no_download:
            self.assertEqual(num_chapters, self.media_reader.download_unread_chapters(any_unread=True))

    def test_bundle(self):
        self._prepare_for_bundle()
        name = self.media_reader.bundle_unread_chapters()
        assert self.media_reader.read_bundle(name)
        self.verify_all_chapters_read()

    def test_bundle_shuffle(self):
        self._prepare_for_bundle()
        names = set()
        for i in range(10):
            names.add(self.media_reader.bundle_unread_chapters(shuffle=True))
        assert names
        assert all(names)

    def test_bundle_no_unreads(self):
        assert not self.media_reader.bundle_unread_chapters()

    def test_bundle_fail(self):
        self._prepare_for_bundle()
        self.settings.bundle_viewer = "exit 1"
        assert not self.media_reader.read_bundle("none.{}".format(self.settings.bundle_format))
        assert not any([x["read"] for media_data in self.media_reader.get_media() for x in media_data["chapters"].values()])

    def test_bundle_anime(self):
        self._prepare_for_bundle(TestAnimeServer.id)
        self.assertFalse(self.media_reader.bundle_unread_chapters())

    def test_stream_anime_bad_url(self):
        assert not self.media_reader.stream("bad_url")

    def test_stream_anime_cont(self):
        self.assertTrue(self.media_reader.stream(TestAnimeServer.stream_url, cont=True) > 1)

    def test_play_anime(self):
        self._prepare_for_bundle(TestAnimeServer.id, no_download=True)
        assert self.media_reader.play(limit=None)
        assert all([x["read"] for media_data in self.media_reader.get_media() for x in media_data["chapters"].values()])

    def test_play_offset_anime(self):
        self.add_test_media(self.media_reader.get_server(TestAnimeServer.id))
        self.media_reader.offset(TestAnimeServer.id, 1)
        chapters = [x for media_data in self.media_reader.get_media() for x in media_data["chapters"].values()]
        assert chapters
        assert [x["read"] for x in chapters if x["number"] <= 0]
        assert self.media_reader.play(limit=None)

        assert all([x["read"] for x in chapters if x["number"] > 0])
        assert not any([x["read"] for x in chapters if x["number"] <= 0])
        assert self.media_reader.play(limit=None, any_unread=True)
        assert all([x["read"] for x in chapters])

    def test_play_anime_downloaded(self):
        self._prepare_for_bundle(TestAnimeServer.id, no_download=False)
        assert self.media_reader.play(limit=None)
        assert all([x["read"] for media_data in self.media_reader.get_media() for x in media_data["chapters"].values()])

    def test_play_anime_single(self):
        self._prepare_for_bundle(TestAnimeServer.id, no_download=True)
        assert self.media_reader.play(limit=1)
        read_dist = [((x["id"], x["number"]), x["read"]) for media_data in self.media_reader.get_media() for x in media_data["chapters"].values()]
        read_dist.sort()
        self.assertEqual(1, sum(map(lambda x: x[1], read_dist)))
        self.assertTrue(read_dist[0][1])


class ApplicationTest(BaseUnitTestClass):

    def test_list(self):
        self.add_test_media()
        self.media_reader.list()

    def test_list_chapters(self):
        self.add_test_media()
        for id in self.media_reader.get_media_ids():
            self.media_reader.list_chapters(id)

    @patch("builtins.input", return_value="0")
    def test_search_add(self, input):
        media_data = self.media_reader.search_add("a")
        assert(media_data)
        assert media_data in list(self.media_reader.get_media())

    @patch("builtins.input", return_value="a")
    def test_search_add_nan(self, input):
        assert not self.media_reader.search_add("a")

    @patch("builtins.input", return_value="1000")
    def test_search_add_out_or_range(self, input):
        assert not self.media_reader.search_add("a")

    @patch("builtins.input", return_value="0")
    def test_load_from_tracker(self, input):
        n = self.media_reader.load_from_tracker(1)
        self.assertTrue(n)
        self.assertEqual(n, len(self.media_reader.get_media_ids()))
        self.assertEqual(0, self.media_reader.load_from_tracker(1))

    def test_select_chapter(self):
        self.media_reader.auto_select = True
        for mediaName in ("Manga", "Anime"):
            with self.subTest(mediaName=mediaName):
                self.assertTrue(self.media_reader.select_chapter(mediaName))


class ApplicationTestWithErrors(BaseUnitTestClass):
    def setUp(self):
        super().setUp()
        self.media_reader.auto_select = True

    def test_search_with_error(self):
        self.test_server.inject_error()
        assert self.media_reader.search_add("manga")
        assert self.test_server.was_error_thrown()

    def test_update_with_error(self):
        self.add_test_media(no_update=True)
        self.test_server.inject_error()
        self.assertRaises(Exception, self.media_reader.update)
        assert self.test_server.was_error_thrown()

    def test_download_with_error(self):
        self.add_test_media()
        self.test_server.inject_error()
        self.assertRaises(Exception, self.media_reader.download_unread_chapters)
        assert self.test_server.was_error_thrown()

    def test_download_with_retry(self):
        self.add_test_media(self.test_server, limit=1)
        self.test_server.inject_error(RetryException("Dummy Retry"))
        assert self.media_reader.download_unread_chapters()
        assert self.test_server.was_error_thrown()
        self.verify_all_chapters_downloaded()

    def test_download_with_repeated_failures(self):
        self.add_test_media(self.test_server, limit=1)
        self.test_server.inject_error(RetryException(None, "Dummy Retry"), -1)
        self.assertRaises(RetryException, self.media_reader.download_unread_chapters)

    def test_download_with_retry_multithreaded(self):
        self.media_reader.settings.threads = 1
        self.add_test_media(self.test_server, limit=1)
        self.test_server.inject_error(RetryException(None, "Dummy Retry"))
        assert self.media_reader.download_unread_chapters()
        assert self.test_server.was_error_thrown()
        self.verify_all_chapters_downloaded()


class CustomTest(MinimalUnitTestClass):
    def setUp(self):
        super().setUp()
        self.setup_customer_server_data()

    def setup_customer_server_data(self):

        for media_type in list(MediaType):
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
        server = self.media_reader.get_server(get_local_server_id(MediaType.MANGA))
        self.add_test_media(server)
        self.assertTrue(self.media_reader.bundle_unread_chapters())

    def test_custom_update(self):
        server = self.media_reader.get_server(get_local_server_id(MediaType.MANGA))
        media_list = self.add_test_media(server)
        assert media_list
        for media_data in media_list:
            assert not self.media_reader.update_media(media_data)


class ArgsTest(MinimalUnitTestClass):
    @patch("builtins.input", return_value="0")
    def test_arg(self, input):
        self.settings.password_manager_enabled = False
        parse_args(media_reader=self.media_reader, args=["auth"])

    def test_test_login(self):
        server = self.media_reader.get_server(TestServerLogin.id)
        self.assertTrue(server.needs_to_login())

        parse_args(media_reader=self.media_reader, args=["login", "--server", server.id])
        self.assertFalse(server.needs_to_login())
        server.reset()
        self.assertTrue(server.needs_to_login())
        parse_args(media_reader=self.media_reader, args=["login"])
        self.assertFalse(server.needs_to_login())

    def test_test_login_fail(self):
        server = self.media_reader.get_server(TestServerLogin.id)
        server.error_login = True
        parse_args(media_reader=self.media_reader, args=["login", "--server", server.id])
        assert server.needs_to_login()

    def test_autocomplete_not_found(self):
        with patch.dict(sys.modules, {"argcomplete": None}):
            parse_args(media_reader=self.media_reader, args=["list"])

    def test_cookies(self):
        key, value = "Key", "value"
        parse_args(media_reader=self.media_reader, args=["add-cookie", TestServer.id, key, value])
        self.assertEqual(self.media_reader.session.cookies.get(key), value)
        parse_args(media_reader=self.media_reader, args=["--clear-cookies", "list"])
        self.assertNotEqual(self.media_reader.session.cookies.get(key), value)

    def test_get_settings(self):
        parse_args(media_reader=self.media_reader, args=["setting", "password_manager_enabled"])

    def test_set_settings(self):
        key_values = [("bundle_format", "jpg"), ("bundle_format", "true"),
                      ("max_retries", "1", 1),
                      ("max_retries", "2", 2),
                      ("password_manager_enabled", "true", True),
                      ("password_manager_enabled", "false", False)]

        self.settings.password_load_cmd = "tmp_value"
        os.environ["AMT_PASSWORD_LOAD_CMD"] = "tmp_env_value"
        for key_value in key_values:
            parse_args(media_reader=self.media_reader, args=["setting", key_value[0], key_value[1]])
            self.media_reader.settings.load()
            self.assertEqual(self.settings.get_field(key_value[0]), key_value[-1])
        del os.environ["AMT_PASSWORD_LOAD_CMD"]
        self.media_reader.settings.reset()
        self.media_reader.settings.load()
        self.assertEqual(Settings.password_load_cmd, self.settings.password_load_cmd)
        for i in range(1, len(key_values), 2):
            self.assertEqual(self.settings.get_field(key_values[i][0]), key_values[i][-1])

    def test_set_settings_server_specific(self):
        self.settings.set_field("force_odd_pages", False)
        key, value = "force_odd_pages", 1
        parse_args(media_reader=self.media_reader, args=["setting", "--target", TestServer.id, key, str(value)])
        self.settings.load()
        self.assertEqual(self.settings.get_field(key, TestServer.id), value)
        self.assertEqual(self.settings.get_field(key), False)

    @patch("getpass.getpass", return_value="0")
    def test_set_password(self, input):
        self.media_reader.settings.password_manager_enabled = True
        self.media_reader.settings.password_load_cmd = "cat {}{} 2>/dev/null".format(TEST_HOME, "{}")
        self.media_reader.settings.password_save_cmd = r"cat - > {}{}".format(TEST_HOME, "{}")
        parse_args(media_reader=self.media_reader, args=["set-password", TestServerLogin.id, "username"])
        self.assertEquals(("username", "0"), self.media_reader.settings.get_credentials(TestServerLogin.id))

    def test_tag(self):
        self.add_test_media()
        tag_name = "test"
        for i in range(2):
            parse_args(media_reader=self.media_reader, args=["untag", tag_name])
            self.assertFalse(any(map(lambda x: x["tags"], self.media_reader.get_media())))
            parse_args(media_reader=self.media_reader, args=["list", "--tag", tag_name])

            parse_args(media_reader=self.media_reader, args=["tag", tag_name])
            self.assertTrue(all(map(lambda x: [tag_name] == x["tags"], self.media_reader.get_media())))
            parse_args(media_reader=self.media_reader, args=["list", "--tag", tag_name])

    def test_print_media_reader_state(self):
        self.add_test_media()
        chapter_id = list(self.media_reader.get_media_ids())[0]
        parse_args(media_reader=self.media_reader, args=["list-chapters", chapter_id])
        parse_args(media_reader=self.media_reader, args=["list"])
        parse_args(media_reader=self.media_reader, args=["list-servers"])

    def test_print_settings_file(self):
        for f in ["settings_file", "metadata", "cookie_file"]:
            parse_args(media_reader=self.media_reader, args=["get-file", f])

    def test_search_save(self):
        parse_args(media_reader=self.media_reader, args=["--auto", "search", "manga"])
        assert len(self.media_reader.get_media_ids())
        self.reload()
        assert len(self.media_reader.get_media_ids())

    def test_select(self):
        parse_args(media_reader=self.media_reader, args=["--auto", "select", "manga"])
        assert not len(self.media_reader.get_media_ids())

    def test_load(self):
        parse_args(media_reader=self.media_reader, args=["--auto", "search", "InProgress"])
        assert len(self.media_reader.get_media_ids()) == 1
        media_data = next(iter(self.media_reader.get_media()))
        parse_args(media_reader=self.media_reader, args=["--auto", "load", "--local-only", "test_user"])
        assert self.media_reader.get_tracker_info(media_data, self.media_reader.get_primary_tracker().id)
        self.assertEqual(media_data["progress"], media_data.get_last_read())

    def test_load_filter_by_type(self):
        parse_args(media_reader=self.media_reader, args=["--auto", "load", f"--media-type={MediaType.ANIME.name}", "test_user"])
        assert all([x["media_type"] == MediaType.ANIME for x in self.media_reader.get_media()])

    def test_load_add_progress_only(self):
        parse_args(media_reader=self.media_reader, args=["--auto", "load", "--progress-only", "test_user"])
        assert not self.media_reader.get_media_ids()

    def test_load_add_new_media(self):
        parse_args(media_reader=self.media_reader, args=["--auto", "load", "test_user"])
        assert len(self.media_reader.get_media_ids()) > 1
        for media_data in self.media_reader.get_media():
            assert self.media_reader.get_tracker_info(media_data, self.media_reader.get_primary_tracker().id)
            if media_data["progress"]:
                self.assertEqual(media_data["progress"], media_data.get_last_read())

    def test_untrack(self):
        parse_args(media_reader=self.media_reader, args=["--auto", "load"])
        assert all([self.media_reader.get_tracker_info(media_data, self.media_reader.get_primary_tracker().id) for media_data in self.media_reader.get_media()])
        parse_args(media_reader=self.media_reader, args=["untrack"])
        assert not any([self.media_reader.get_tracker_info(media_data, self.media_reader.get_primary_tracker().id) for media_data in self.media_reader.get_media()])

    def test_copy_tracker(self):
        media_list = self.add_test_media()
        self.media_reader.get_primary_tracker().set_custom_anime_list([media_list[0]["name"]], media_list[0]["media_type"])
        parse_args(media_reader=self.media_reader, args=["--auto", "load", "test_user"])
        assert self.media_reader.get_tracker_info(media_list[0])
        assert not self.media_reader.get_tracker_info(media_list[1])
        parse_args(media_reader=self.media_reader, args=["copy-tracker", media_list[0]["name"], media_list[1]["name"]])
        self.assertEquals(self.media_reader.get_tracker_info(media_list[0]), self.media_reader.get_tracker_info(media_list[1]))

    def test_stats(self):
        self.add_test_media()
        parse_args(media_reader=self.media_reader, args=["stats", "test_user"])
        parse_args(media_reader=self.media_reader, args=["stats", "--media-type", MediaType.ANIME.name, "test_user"])
        parse_args(media_reader=self.media_reader, args=["stats", "-s", "NAME", "test_user"])
        parse_args(media_reader=self.media_reader, args=["stats", "-g", "NAME", "test_user"])
        parse_args(media_reader=self.media_reader, args=["stats", "--details", "-d", "NAME", "test_user"])

    def test_stats_default_user(self):
        self.add_test_media()
        parse_args(media_reader=self.media_reader, args=["stats"])

    def test_stats_refresh(self):
        self.add_test_media()
        parse_args(media_reader=self.media_reader, args=["stats", "--refresh"])
        parse_args(media_reader=self.media_reader, args=["stats"])
        parse_args(media_reader=self.media_reader, args=["stats", "--refresh"])

    def test_mark_read(self):
        media_list = self.add_test_media()
        media_data = media_list[0]
        name = media_data.global_id
        parse_args(media_reader=self.media_reader, args=["mark-read", name])
        assert all(map(lambda x: x["read"], media_data["chapters"].values()))
        parse_args(media_reader=self.media_reader, args=["mark-read", "--force", name, "-1"])
        assert not all(map(lambda x: x["read"], media_data["chapters"].values()))
        parse_args(media_reader=self.media_reader, args=["mark-unread", name])
        assert not any(map(lambda x: x["read"], media_data["chapters"].values()))

    def test_sync_progress(self):
        parse_args(media_reader=self.media_reader, args=["--auto", "load"])
        parse_args(media_reader=self.media_reader, args=["mark-read"])
        parse_args(media_reader=self.media_reader, args=["sync"])
        for i in range(2):
            for media_data in self.media_reader.get_media():
                self.assertEqual(media_data.get_last_chapter_number(), media_data.get_last_read())
                self.assertEqual(media_data["progress"], media_data.get_last_read())
            self.reload()

    def test_download(self):
        self.add_test_media(limit=1)
        parse_args(media_reader=self.media_reader, args=["download-unread"])
        self.verify_all_chapters_downloaded()

    def test_download_specific(self):
        media_list = self.add_test_media()
        media_data = media_list[0]
        chapters = media_data.get_sorted_chapters()
        parse_args(media_reader=self.media_reader, args=["download", media_data.global_id, str(chapters[1]["number"]), str(chapters[-2]["number"])])
        for chapter_data in chapters[1:-2]:
            self.verify_download(media_data, chapter_data)

    def test_download_specific_single(self):
        media_list = self.add_test_media()
        media_data = media_list[0]
        chapters = media_data.get_sorted_chapters()
        parse_args(media_reader=self.media_reader, args=["download", media_data.global_id, str(chapters[1]["number"])])
        self.verify_download(media_data, chapters[1])

        server = self.media_reader.get_server(media_data["server_id"])
        for chapter_data in chapters:
            if chapter_data != chapters[1]:
                assert not server.is_fully_downloaded(media_data, chapter_data)

    def test_download_next(self):
        self.add_test_media(self.test_server)
        for id, media_data in self.media_reader.media.items():
            server = self.media_reader.get_server(media_data["server_id"])
            chapter = list(media_data.get_sorted_chapters())[0]
            parse_args(media_reader=self.media_reader, args=["download-unread", "--limit", "1", id])
            self.assertEqual(0, server.download_chapter(media_data, chapter))

    def test_update(self):
        media_list = self.add_test_media(no_update=True)
        self.assertEqual(len(media_list[0]["chapters"]), 0)
        parse_args(media_reader=self.media_reader, args=["update"])
        self.assertTrue(media_list[0]["chapters"])

    def test_update_replace(self):
        fake_chapter_id = "fakeId"
        media_list = self.add_test_media()
        original_len = len(media_list[0]["chapters"])
        media_list[0]["chapters"][fake_chapter_id] = dict(list(media_list[0]["chapters"].values())[0])
        self.media_reader.mark_read()
        parse_args(media_reader=self.media_reader, args=["update", "--replace"])
        assert fake_chapter_id not in media_list[0]["chapters"]
        assert original_len == len(media_list[0]["chapters"])
        self.verify_all_chapters_read()

    def test_offset(self):
        media_list = self.add_test_media()
        media_data = media_list[0]
        chapters = media_data["chapters"]
        list_of_numbers = sorted([chapter_data["number"] for chapter_data in chapters.values()])
        offset_list = list(map(lambda x: x - 1, list_of_numbers))
        parse_args(media_reader=self.media_reader, args=["offset", media_data.global_id, "1"])
        self.assertEqual(offset_list, sorted([chapter_data["number"] for chapter_data in chapters.values()]))
        self.verify_unique_numbers(media_data["chapters"])

    def test_offset_update(self):
        media_data = self.add_test_media(limit=1)[0]
        chapters = media_data["chapters"]
        list_of_numbers = sorted([chapter_data["number"] for chapter_data in chapters.values()])
        offset_list = list(map(lambda x: x - 1, list_of_numbers))
        parse_args(media_reader=self.media_reader, args=["offset", media_data.global_id, "1"])
        self.assertEqual(offset_list, sorted([chapter_data["number"] for chapter_data in chapters.values()]))
        parse_args(media_reader=self.media_reader, args=["update"])
        self.assertEqual(offset_list, sorted([chapter_data["number"] for chapter_data in chapters.values()]))

    def test_search(self):
        parse_args(media_reader=self.media_reader, args=["--auto", "search", "manga"])
        self.assertRaises(ValueError, parse_args, media_reader=self.media_reader, args=["--auto", "search", "manga"])

    def test_search_fail(self):
        parse_args(media_reader=self.media_reader, args=["--auto", "search", "__UnknownMedia__"])

    def test_migrate_offset(self):
        media_data = self.add_test_media(self.test_server)[0]
        parse_args(media_reader=self.media_reader, args=["offset", media_data.global_id, "1"])
        parse_args(media_reader=self.media_reader, args=["migrate", "--self", media_data["name"]])
        for i in range(2):
            media_data = self.media_reader.get_single_media(name=media_data.global_id)
            self.assertEqual(media_data["offset"], 1)
            self.media_reader.state.all_media["version"] = 0
            self.media_reader.upgrade_state()

    def test_migrate(self):

        media_list = self.add_test_media(self.test_server)
        parse_args(media_reader=self.media_reader, args=["--auto", "load", "--local-only"])
        self.media_reader.mark_read()
        parse_args(media_reader=self.media_reader, args=["--auto", "migrate", "--exact", self.test_server.id])
        self.assertEqual(len(self.media_reader.get_media_ids()), len(media_list))

        for media_data in media_list:
            media_data2 = self.media_reader.get_single_media(name=media_data["name"])
            if not media_data.get("unique", False):
                self.assertNotEqual(media_data.global_id, media_data2.global_id)
            self.assertEqual(media_data.get_last_read(), media_data2.get_last_read())
            self.assertEqual(media_data["progress"], media_data2["progress"])
            self.assertEqual(self.media_reader.get_tracker_info(media_data), self.media_reader.get_tracker_info(media_data2))

    def test_migrate_self(self):
        media_list = self.add_test_media(self.test_server)
        parse_args(media_reader=self.media_reader, args=["--auto", "load", "--local-only"])
        self.media_reader.mark_read()
        parse_args(media_reader=self.media_reader, args=["--auto", "migrate", "--self", "--force-same-id", self.test_server.id])
        self.assertEqual(len(self.media_reader.get_media_ids()), len(media_list))

        for media_data in media_list:
            self.assertEqual(media_data, self.media_reader.get_single_media(media_data.global_id))

    def test_remove(self):
        parse_args(media_reader=self.media_reader, args=["--auto", "search", "manga"])
        media_id = list(self.media_reader.get_media_ids())[0]
        parse_args(media_reader=self.media_reader, args=["remove", media_id])
        self.verify_no_media()

    def test_clean_bundle(self):
        self.add_test_media(self.test_server)
        parse_args(media_reader=self.media_reader, args=["bundle"])
        parse_args(media_reader=self.media_reader, args=["clean", "-b"])
        self.assertEqual(0, len(self.media_reader.bundles))
        self.assertFalse(os.listdir(self.settings.bundle_dir))
        parse_args(media_reader=self.media_reader, args=["bundle"])

    def test_clean_removed(self):
        self.add_test_media(self.test_server)
        self.media_reader.download_unread_chapters()
        self.media_reader.media.clear()

        parse_args(media_reader=self.media_reader, args=["clean"])
        for dir in os.listdir(self.settings.media_dir):
            self.assertEqual(0, len(os.listdir(os.path.join(self.settings.media_dir, dir))))

    def test_clean_read(self):
        self.add_test_media(self.test_server)
        self.media_reader.download_unread_chapters()
        self.media_reader.mark_read()
        parse_args(media_reader=self.media_reader, args=["clean", "--remove-read"])
        self.verify_no_chapters_downloaded()

    def test_clean_servers(self):
        self.add_test_media(self.test_server)
        self.media_reader.download_unread_chapters()
        self.media_reader._servers.clear()
        parse_args(media_reader=self.media_reader, args=["clean", "--remove-disabled-servers"])
        self.assertEqual(0, len(os.listdir(self.settings.media_dir)))

    def test_clean_unused(self):
        self.add_test_media(self.test_server)
        parse_args(media_reader=self.media_reader, args=["clean", "--remove-not-on-disk"])
        self.assertEqual(0, len(os.listdir(self.settings.get_server_dir(TestServer.id))))

    def test_bundle_read(self):
        media_list = self.add_test_media(self.test_server)

        self.media_reader.download_unread_chapters()
        parse_args(media_reader=self.media_reader, args=["bundle"])
        assert len(self.media_reader.bundles)
        name, bundle_data = list(self.media_reader.bundles.items())[0]
        self.assertTrue(os.path.isabs(name))
        self.assertTrue(os.path.exists(name))
        self.assertEqual(len(bundle_data), sum([len(x["chapters"]) for x in media_list]))
        parse_args(media_reader=self.media_reader, args=["read", os.path.basename(name)])
        self.verify_all_chapters_read(MediaType.MANGA)

    def test_bundle_read_simple(self):
        self.add_test_media(self.test_server)
        parse_args(media_reader=self.media_reader, args=["bundle"])
        parse_args(media_reader=self.media_reader, args=["read"])
        self.verify_all_chapters_read(MediaType.MANGA)

    def test_bundle_download_error(self):
        server = self.media_reader.get_server(TestServerLogin.id)
        self.add_test_media(server)
        server.error_login = True
        self.assertRaises(ValueError, parse_args, media_reader=self.media_reader, args=["bundle", TestServerLogin.id])
        assert not self.media_reader.bundles

    def test_bundle_specific(self):
        media_list = self.add_test_media(self.test_server)
        self.media_reader.download_unread_chapters()
        num_chapters = sum([len(x["chapters"]) for x in media_list])
        fake_data = self.test_server.create_media_data("-1", "Fake Data")
        fake_data["server_id"] = "unique_id"
        self.test_server.update_chapter_data(fake_data, 1, "Fake chapter", 1)
        self.media_reader.add_media(fake_data, no_update=True)
        parse_args(media_reader=self.media_reader, args=["bundle", self.test_server.id])
        self.assertEqual(len(list(self.media_reader.bundles.values())[0]), num_chapters)
        self.media_reader.bundles.clear()
        media_data = media_list[0]
        for name in (media_data["name"], media_data.global_id):
            parse_args(media_reader=self.media_reader, args=["bundle", str(name)])
            self.assertEqual(len(list(self.media_reader.bundles.values())[0]), len(media_data["chapters"]))
            self.media_reader.bundles.clear()

    def test_bundle_limit(self):
        self.add_test_media(self.test_server)
        parse_args(media_reader=self.media_reader, args=["bundle", "--limit=2"])
        bundle_data = list(self.media_reader.bundles.values())[0]
        self.assertEqual(len(bundle_data), 2)

    def test_play(self):
        self.add_test_media()
        parse_args(media_reader=self.media_reader, args=["play"])
        self.verify_all_chapters_read()

    def test_play_fail(self):
        self.add_test_media(self.test_anime_server)

        self.settings.viewer = "exit 1"
        parse_args(media_reader=self.media_reader, args=["play"])
        assert not self.get_num_chapters_read(MediaType.ANIME)

    def test_play_specific(self):
        media_data = self.add_test_media(self.test_anime_server)[0]
        parse_args(media_reader=self.media_reader, args=["play", media_data["name"], "1", "3"])
        for chapter in media_data.get_sorted_chapters():
            self.assertEquals(chapter["read"], chapter["number"] in [1, 3])

    def test_play_relative(self):
        media_data = self.add_test_media(self.test_anime_server, limit=1)[0]
        chapters = list(media_data.get_sorted_chapters())
        chapters[1]["read"] = True
        parse_args(media_reader=self.media_reader, args=["play", media_data["name"], "-1"])
        assert chapters[0]["read"]

    def test_play_last_read(self):
        media_data = self.add_test_media(self.test_anime_server, limit=1)[0]
        chapters = list(media_data.get_sorted_chapters())
        chapters[1]["read"] = True
        parse_args(media_reader=self.media_reader, args=["play", media_data["name"], "0"])
        self.assertEquals(1, self.get_num_chapters_read(MediaType.ANIME))

    def test_get_stream_url(self):
        self.add_test_media(self.test_anime_server)
        parse_args(media_reader=self.media_reader, args=["get-stream-url"])
        assert not self.get_num_chapters_read(MediaType.ANIME)

    def test_stream(self):
        parse_args(media_reader=self.media_reader, args=["stream", TestAnimeServer.stream_url])
        self.verify_no_media()

    def test_stream_quality(self):
        parse_args(media_reader=self.media_reader, args=["stream", "-q", "-1", TestAnimeServer.stream_url])

    def test_stream_download(self):
        parse_args(media_reader=self.media_reader, args=["stream", "--download", TestAnimeServer.stream_url])
        self.verify_no_media()
        server = self.media_reader.get_server(TestAnimeServer.id)
        media_data = server.get_media_data_from_url(TestAnimeServer.stream_url)
        chapter_data = media_data["chapters"][server.get_chapter_id_for_url(TestAnimeServer.stream_url)]
        self.verify_download(media_data, chapter_data)

    def test_download_stream(self):
        parse_args(media_reader=self.media_reader, args=["stream", "--download", TestAnimeServer.stream_url])
        parse_args(media_reader=self.media_reader, args=["stream", TestAnimeServer.stream_url])

    def test_add_from_url_stream_cont(self):
        parse_args(media_reader=self.media_reader, args=["add-from-url", TestAnimeServer.stream_url])
        parse_args(media_reader=self.media_reader, args=["stream", "--cont", TestAnimeServer.stream_url])
        self.verify_all_chapters_read(MediaType.ANIME)

    def test_add_from_url_bad(self):
        self.assertRaises(ValueError, parse_args, media_reader=self.media_reader, args=["add-from-url", "bad-url"])
        self.verify_no_media()

    def test_import_auto_detect_name(self):
        samples = [
            (MediaType.ANIME, "Banner of the Stars", 1, "01. Banner of the Stars (Seikai no Senki) [480p][author].mkv"),
            (MediaType.ANIME, "Magical Girl Lyrical Nanoha", 13, "[author] Magical Girl Lyrical Nanoha - 13 (type) [deadbeef].mkv"),
            (MediaType.ANIME, "Magical Girl Lyrical Nanoha A's", 999, "[author] Magical Girl Lyrical Nanoha A's - 999.mkv"),
            (MediaType.ANIME, "Steins;Gate", 1, "01 - Steins;Gate.mkv"),
            (MediaType.ANIME, "Kaguya-sama", 1, "Kaguya-sama - 01.mkv"),
            (MediaType.ANIME, "ViVid Strike!", 1, "[First Name] ViVid Strike! - 01 [BD 1080p][247EFC8F].mkv"),
            (MediaType.ANIME, "Specials", 5.5, "[First Name] Specials - 05.5 [BD 1080p][247EFC8F].mkv"),
            (MediaType.ANIME, "Ending", 0, "[First Name] Ending - ED [BD 1080p][247EFC8F].mkv"),
            (MediaType.ANIME, "Attack No. 1", 2, "Attack No. 1 - 02.mkv"),
            (MediaType.ANIME, "Alien 9", 1, "[author] Alien 9 - OVA 01 [English Sub] [Dual-Audio] [480p].mkv"),
            (MediaType.MANGA, "shamanking0", 1, "shamanking0_vol1.pdf"),
            (MediaType.NOVEL, "i-refuse-to-be-your-enemy", 5, "i-refuse-to-be-your-enemy-volume-5.epub"),
            (MediaType.ANIME, "Minami-ke", 2, "Minami-ke - S01E02.mkv"),
        ]

        self.settings.viewer = "[ -f {media} ]"
        for media_type, name, number, file_name in samples:
            with self.subTest(file_name=file_name):
                with open(file_name, "w") as f:
                    f.write("dummy_data")
                assert os.path.exists(file_name)
                parse_args(media_reader=self.media_reader, args=["import", "--media-type", media_type.name, file_name])
                assert not os.path.exists(file_name)
                assert any([x["name"] == name for x in self.media_reader.get_media()])
                for media_data in self.media_reader.get_media():
                    if media_data["name"] == name:
                        chapters = list(media_data["chapters"].values())
                        self.assertEqual(len(chapters), 1)
                        self.assertEqual(chapters[0]["number"], number)
                        assert re.search(r"^\w+$", media_data["id"])
                        self.assertEqual(media_data["media_type"], media_type)
                        assert self.media_reader.play(name, any_unread=True)

    def test_import_directory(self):
        path = os.path.join(TEST_HOME, "test-dir")
        os.mkdir(path)
        path_file = os.path.join(path, "Anime1 - E10.jpg")
        with open(path_file, "w") as f:
            f.write("dummy_data")
        parse_args(media_reader=self.media_reader, args=["import", path])
        assert any([x["name"] == "Anime1" for x in self.media_reader.get_media()])

    def test_import_multiple(self):
        file_names = ["Media - 1.mp4", "MediaOther - 1.mp4", "Media - 2.mp4"]
        file_names2 = ["Media - 3.mp4", "MediaOther - 2.mp4", "Media - 4.mp4"]
        for name in file_names + file_names2:
            with open(name, "w") as f:
                f.write("dummy_data")
        for name_list in (file_names, file_names2):
            parse_args(media_reader=self.media_reader, args=["import", f"--media-type={MediaType.ANIME.name}"] + name_list)
            self.assertEqual(2, len(self.media_reader.get_media_ids()))
            for name in name_list:
                with self.subTest(file_name=name):
                    assert any([x["name"] == name.split()[0] for x in self.media_reader.get_media()])

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
        parse_args(media_reader=self.media_reader, args=["import", "--link", path])
        self.assertEqual(1, len(self.media_reader.get_media_ids()))
        assert os.path.exists(path)
        parse_args(media_reader=self.media_reader, args=["import", "--name", "testMedia", path2])
        assert 2 == len(self.media_reader.get_media_ids())
        assert any([x["name"] == "testMedia" for x in self.media_reader.get_media()])
        assert not os.path.exists(path2)

        for i, media_type in enumerate(list(MediaType)):
            name = "name" + str(i)
            parse_args(media_reader=self.media_reader, args=["import", "--link", "--name", name, "--media-type", media_type.name, path3])
            assert any([x["name"] == name for x in self.media_reader.get_media()])
            self.assertEqual(3 + i, len(self.media_reader.get_media_ids()))
            assert os.path.exists(path3)

    def _test_upgrade_helper(self, minor):
        self.add_test_media(self.test_anime_server)
        ids = list(self.media_reader.get_media_ids())
        removed_key = "removed_key"
        new_key = "alt_id"
        self.media_reader.media[ids[0]][removed_key] = False
        del self.media_reader.media[ids[0]][new_key]
        next(iter(self.media_reader.media[ids[1]]["chapters"].values())).pop("special")
        self.media_reader.mark_read()

        next(iter(self.media_reader.media[ids[2]]["chapters"].values()))["old_chapter_field"] = 10

        self.media_reader.state.update_verion()
        self.media_reader.state.all_media["version"] -= .1 if minor else 1
        self.assertEqual(self.media_reader.state.is_out_of_date_minor(), minor)
        parse_args(media_reader=self.media_reader, args=["upgrade" if not minor else "list"])
        self.assertEqual(list(self.media_reader.get_media_ids()), ids)
        self.assertEqual(removed_key in self.media_reader.media[ids[0]], minor)
        self.assertTrue(new_key in self.media_reader.media[ids[0]])
        if not minor:
            self.assertTrue(all(["special" in x for x in self.media_reader.media[ids[1]]["chapters"].values()]))
            self.assertTrue(all(["old_chapter_field" not in x for x in self.media_reader.media[ids[2]]["chapters"].values()]))
        self.assertTrue(all([media_data.get_last_read() == media_data.get_last_chapter_number() for media_data in self.media_reader.get_media()]))

    def test_upgrade_minor(self):
        self._test_upgrade_helper(True)

    def test_upgrade_major(self):
        self._test_upgrade_helper(False)

    def test_upgrade_change_in_chapter_format_as_needed(self):
        media_list = self.add_test_media(self.test_anime_server)
        for media_data in media_list:
            assert media_data.chapters
            media_data["chapters"] = media_data.chapters
            media_data.chapters = {}
        self.media_reader.save()
        self.reload()
        for media_data in self.media_reader.get_media():
            assert media_data.chapters


class ServerTest(RealBaseUnitTestClass):
    def setUp(self):
        super().setUp()

    def test_workflow(self):
        def func(server):
            media_list = None
            with self.subTest(server=server.id, list=True):
                media_list = server.get_media_list()
                assert media_list or not server.has_free_chapters
                assert isinstance(media_list, list)
                assert all([isinstance(x, dict) for x in media_list])
                assert all([x["media_type"] == server.media_type for x in media_list])

            with self.subTest(server=server.id, list=False):
                search_media_list = server.search(media_list[0]["name"] if media_list else "One", limit=1)
                assert search_media_list or not server.has_free_chapters
                assert isinstance(search_media_list, list)
                assert all([isinstance(x, dict) for x in search_media_list])

            for media_data in media_list:
                self.media_reader.add_media(media_data)
                for chapter_data in filter(lambda x: not x["premium"] and not x["inaccessible"], media_data["chapters"].values()):
                    with self.subTest(server=server.id, stream=True):
                        if media_data["media_type"] & MediaType.ANIME:
                            assert self.media_reader.play(media_data.global_id, num_list=[chapter_data["number"]])
                    if not os.getenv("SKIP_DOWNLOAD"):
                        with self.subTest(server=server.id, stream=False):
                            self.assertNotEqual(server.external, server.download_chapter(media_data, chapter_data, page_limit=2))
                            self.verify_download(media_data, chapter_data)
                            assert not server.download_chapter(media_data, chapter_data, page_limit=1)
                    return True
        self.for_each(func, self.media_reader.get_servers())

    def test_login_fail(self):
        self.media_reader.settings.password_manager_enabled = True
        self.media_reader.settings.password_load_cmd = r"echo -e A\\tB"

        def func(server_id):
            server = self.media_reader.get_server(server_id)
            try:
                with self.subTest(server=server.id, method="relogin"):
                    assert not server.relogin()
            finally:
                assert server.needs_to_login()

        self.for_each(func, self.media_reader.get_servers_ids_with_logins())


class ServerStreamTest(RealBaseUnitTestClass):
    streamable_urls = [
        ("https://j-novel.club/read/i-refuse-to-be-your-enemy-volume-1-part-1", "i-refuse-to-be-your-enemy", None, "i-refuse-to-be-your-enemy-volume-1-part-1"),
        ("https://j-novel.club/read/seirei-gensouki-spirit-chronicles-manga-volume-1-chapter-1", "seirei-gensouki-spirit-chronicles-manga", None, "seirei-gensouki-spirit-chronicles-manga-volume-1-chapter-1"),
        ("https://mangadex.org/chapter/ea697e18-470c-4e80-baf0-a3972720178f/1", "8a3d319d-2d10-4364-928c-0f30fd367c24", None, "ea697e18-470c-4e80-baf0-a3972720178f"),
        ("https://mangaplus.shueisha.co.jp/viewer/1000486", "100020", None, "1000486"),
        ("https://mangasee123.com/read-online/Bobobo-Bo-Bo-Bobo-chapter-214-page-1.html", "Bobobo-Bo-Bo-Bobo", None, "102140"),
        ("https://vrv.co/watch/GR3VWXP96/One-Piece:Im-Luffy-The-Man-Whos-Gonna-Be-King-of-the-Pirates", "GRMG8ZQZR", "GYVNM8476", "GR3VWXP96"),
        ("https://www.crunchyroll.com/gintama/gintama-season-2-253-265-gintama-classic-it-takes-a-bit-of-courage-to-enter-a-street-vendors-stand-615207", "47620", "20725", "615207"),
        ("https://www.crunchyroll.com/manga/to-your-eternity/read/1", "499", None, "16329"),
        ("https://www.crunchyroll.com/one-piece/episode-1-im-luffy-the-man-whos-gonna-be-king-of-the-pirates-650673", "257631", "21685", "650673"),
        ("https://www.crunchyroll.com/rezero-starting-life-in-another-world-/episode-31-the-maidens-gospel-796209", "269787", "25186", "796209"),
        ("https://www.crunchyroll.com/the-irregular-at-magic-high-school/episode-1-enrollment-part-i-652193", "260315", "21563", "652193"),
        ("https://www.funimation.com/en/shows/one-piece/im-luffy-the-man-whos-gonna-be-king-of-the-pirates/?lang=japanese", "20224", "20227", "22333"),
        ("https://www.funimation.com/en/shows/one-piece/im-luffy-the-man-whos-gonna-be-king-of-the-pirates/?lang=english", "20224", "20227", "22338"),
        ("https://www.viz.com/shonenjump/one-piece-chapter-1/chapter/5090?action=read", "one-piece", None, "5090"),
        ("https://www.wlnupdates.com/series-id/49815/itai-no-wa-iya-nanode-bogyo-ryoku-ni-kyokufuri-shitai-to-omoimasu", "49815", None, None),
    ]

    premium_streamable_urls = [
        ("https://www.funimation.com/shows/bofuri-i-dont-want-to-get-hurt-so-ill-max-out-my-defense/defense-and-first-battle/?lang=japanese", "1019573", "1019574", "1019900"),
        ("https://www.funimation.com/shows/the-irregular-at-magic-high-school/visitor-arc-i/simulcast/?lang=japanese&qid=f290b76b82d5938b", "1079937", "1174339", "1174543"),
    ]

    @unittest.skipIf(os.getenv("ENABLE_ONLY_SERVERS"), "Not all servers are enabled")
    def test_verify_valid_stream_urls(self):
        for url, media_id, season_id, chapter_id in self.streamable_urls:
            with self.subTest(url=url):
                servers = list(filter(lambda server: server.can_stream_url(url), self.media_reader.get_servers()))
                self.assertEqual(len(servers), 1)

    def test_media_add_from_url(self):
        def func(url_data):
            url, media_id, season_id, chapter_id = url_data
            with self.subTest(url=url):
                servers = list(filter(lambda server: server.can_stream_url(url), self.media_reader.get_servers()))
                self.assertTrueOrSkipTest(servers)
                for server in servers:
                    with self.subTest(url=url, server=server.id):
                        media_data = server.get_media_data_from_url(url)
                        assert media_data
                        server.update_media_data(media_data)
                        self.assertEqual(media_id, str(media_data["id"]))
                        if season_id:
                            self.assertEqual(season_id, str(media_data["season_id"]))
                        if chapter_id:
                            self.assertTrue(chapter_id in media_data["chapters"])
                            self.assertEqual(chapter_id, str(server.get_chapter_id_for_url(url)))
                            self.assertEqual(str(server.get_chapter_id_for_url(url)), str(chapter_id))
                            self.assertTrue(chapter_id in media_data["chapters"])
                        assert self.media_reader.add_from_url(url)
        self.for_each(func, self.streamable_urls)

    def test_media_steam(self):
        url_list = self.streamable_urls if not os.getenv("PREMIUM_TEST") else self.streamable_urls + self.premium_streamable_urls

        def func(url_data):
            url, media_id, season_id, chapter_id = url_data
            with self.subTest(url=url):
                servers = list(filter(lambda server: server.can_stream_url(url), self.media_reader.get_servers()))
                self.assertTrueOrSkipTest(servers)
                for server in servers:
                    if server.media_type == MediaType.ANIME:
                        assert self.media_reader.stream(url)
        self.for_each(func, url_list)


class TrackerTest(RealBaseUnitTestClass):

    def test_num_trackers(self):
        assert self.media_reader.get_primary_tracker()
        assert self.media_reader.get_secondary_trackers()

    def test_get_list(self):
        for tracker in self.media_reader.get_trackers():
            with self.subTest(tracker=tracker.id):
                data = list(tracker.get_tracker_list(id=1))
                assert data
                assert isinstance(data[0], dict)

    def test_no_auth(self):
        self.settings.password_manager_enabled = False
        for tracker in self.media_reader.get_trackers():
            if tracker.id != TestTracker.id:
                with self.subTest(tracker=tracker.id):
                    self.assertRaises(ValueError, tracker.update, [])

    @patch("builtins.input", return_value="0")
    def test_arg(self, input):
        self.settings.password_manager_enabled = False
        for tracker in self.media_reader.get_trackers():
            self.media_reader.set_primary_tracker(tracker)
            parse_args(media_reader=self.media_reader, args=["auth"])

    @unittest.skipIf(os.getenv("ENABLE_ONLY_SERVERS"), "Not all servers are enabled")
    def test_load_stats(self):
        for tracker in self.media_reader.get_trackers():
            if tracker.id != TestTracker.id:
                self.media_reader.set_primary_tracker(tracker)
                parse_args(media_reader=self.media_reader, args=["--auto", "load", "--user-id=1"])
                self.assertTrue(self.media_reader.get_media_ids())
                parse_args(media_reader=self.media_reader, args=["stats", "--user-id=1"])


class RealArgsTest(RealBaseUnitTestClass):

    @unittest.skipIf(os.getenv("ENABLE_ONLY_SERVERS"), "Not all servers are enabled")
    def test_load_from_tracker(self):
        anime = ["HAIKYU!! To the Top", "Kaij: Ultimate Survivor", "Re:Zero", "Steins;Gate"]
        self.media_reader.get_primary_tracker().set_custom_anime_list(anime)
        parse_args(media_reader=self.media_reader, args=["--auto", "load", f"--media-type={MediaType.ANIME.name}"])
        self.assertEqual(len(anime), len(self.media_reader.get_media_ids()))


class ServerSpecificTest(RealBaseUnitTestClass):

    def test_wlnupdates_complex_entry(self):
        from ..servers.wlnupdates import WLN_Updates
        server = self.media_reader.get_server(WLN_Updates.id)
        self.assertTrueOrSkipTest(server)
        url = "https://www.wlnupdates.com/series-id/49815/itai-no-wa-iya-nanode-bogyo-ryoku-ni-kyokufuri-shitai-to-omoimasu"
        self.media_reader.add_from_url(url)
        media_data = list(self.media_reader.get_media())[0]
        self.verify_unique_numbers(media_data["chapters"])
        for i in range(2):
            self.media_reader.update()
            self.verify_unique_numbers(media_data["chapters"])

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
        assert server.needs_authentication()

    def test_jnovel_club_manga_parts_full_download(self):
        from ..servers.jnovelclub import JNovelClubMangaParts
        server = self.media_reader.get_server(JNovelClubMangaParts.id)
        self.assertTrueOrSkipTest(server)
        media_data = server.get_media_list()[0]
        self.media_reader.add_media(media_data)
        self.assertTrue(media_data["chapters"])
        self.media_reader.download_unread_chapters(name=media_data.global_id, limit=1, page_limit=7)

    def test_jnovel_club_parts_autodelete(self):
        from ..servers.jnovelclub import JNovelClubParts
        server = self.media_reader.get_server(JNovelClubParts.id)
        self.assertTrueOrSkipTest(server)
        server.time_to_live_sec = 0
        media_data = server.get_media_list()[0]
        self.media_reader.add_media(media_data)
        self.assertTrue(media_data["chapters"])
        self.media_reader.download_unread_chapters(name=media_data.global_id, limit=1)

        self.assertTrue(media_data["chapters"])
        self.assertTrue(os.path.exists(self.settings.get_media_dir(media_data)))
        self.media_reader.update(name=media_data.global_id)
        self.assertTrue(media_data["chapters"])

        self.assertTrue(os.path.exists(self.settings.get_media_dir(media_data)))
        for chapter_data in media_data["chapters"].values():
            chapter_path = self.settings.get_chapter_dir(media_data, chapter_data, skip_create=True)
            self.assertFalse(os.path.exists(chapter_path))

    def test_search_for_long_running_media(self):
        interesting_media = ["Gintama", "One Piece"]

        def func(media):
            with self.subTest(media_name=media):
                media_data = self.media_reader.search_for_media(media, media_type=MediaType.ANIME, limit=2, raiseException=True)
                self.assertTrueOrSkipTest(media)
                for data in media_data:
                    self.media_reader.add_media(data, no_update=True)
        self.for_each(func, interesting_media)
        self.media_reader.update()
        for media_data in self.media_reader.get_media():
            self.verify_unique_numbers(media_data["chapters"])


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
        assert self.media_reader.test_login()
        for server in self.media_reader.get_servers():
            if server.has_login:
                with self.subTest(server=server.id):
                    assert not server.needs_authentication()


def load_tests(loader, tests, pattern):

    clazzes = inspect.getmembers(sys.modules[__name__], inspect.isclass)
    test_cases = [c for _, c in clazzes if issubclass(c, BaseUnitTestClass)]
    test_cases.sort(key=lambda f: findsource(f)[1])
    suite = unittest.TestSuite()
    for test_class in test_cases:
        tests = loader.loadTestsFromTestCase(test_class)
        suite.addTests(tests)
    return suite
