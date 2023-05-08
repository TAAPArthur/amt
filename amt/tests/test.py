import inspect
import json
import logging
import os
import requests
import shutil
import subprocess
import sys
import time
import unittest

from inspect import findsource
from requests.exceptions import ConnectionError
from subprocess import CalledProcessError
from unittest.mock import patch

from .. import servers, tests
from ..args import parse_args, setup_subparsers, init_logger
from ..job import Job, RetryException
from ..media_reader import SERVERS, MediaReader, import_sub_classes
from ..media_reader_cli import MediaReaderCLI
from ..server import RequestServer
from ..servers.local import LocalServer
from ..servers.remote import RemoteServer
from ..settings import Settings
from ..state import ChapterData, MediaData, State
from ..util.exceptions import ChapterLimitException
from ..util.media_type import MediaType
from .test_server import (TEST_BASE, TestAnimeServer, TestServer, TestUnofficialServer, TestServerLogin, TestServerLoginAnime)
from .test_tracker import TestTracker

HAS_PIL = True
try:
    from PIL import Image

    from ..util.decoder import GenericDecoder
    # Make the tests faster for certain servers
    GenericDecoder.PENDING_CACHE_NUM = 1
except:
    HAS_PIL = False


TEST_HOME = TEST_BASE + "test_home/"
TEST_TEMP = TEST_BASE + "tmp/"


TEST_SERVERS = import_sub_classes(tests, TestServer)
TEST_TRACKERS = import_sub_classes(tests, TestTracker)
LOCAL_SERVERS = import_sub_classes(servers, LocalServer)

SKIP_DOWNLOAD = os.getenv("SKIP_DOWNLOAD")
SINGLE_THREADED = os.getenv("DEBUG")
PREMIUM_TEST = os.getenv("PREMIUM_TEST")
QUICK_TEST = os.getenv("QUICK")
ENABLED_SERVERS = os.getenv("AMT_ENABLED_SERVERS")
DISABLED_SERVERS = os.getenv("AMT_DISABLED_SERVERS")
ALLOW_CLOUD_SCRAPER_FAILURES = os.getenv("ALLOW_CLOUD_SCRAPER_FAILURES")


class BaseUnitTestClass(unittest.TestCase):
    real = False
    cli = False
    media_reader = None
    default_server_list = list(TEST_SERVERS)

    def __init__(self, methodName="runTest"):
        super().__init__(methodName=methodName)
        self.init()

    def init(self):
        pass

    def close_sessions(self):
        self.media_reader.session.close()
        for server in self.media_reader.get_servers():
            if server.session != self.media_reader.session:
                server.session.close()

    def reload(self, set_settings=False, save_settings=False, keep_settings=False, save_state=False):
        if self.media_reader:
            self.close_sessions()

        RequestServer.cloudscraper = None

        cls = MediaReaderCLI if self.cli else MediaReader
        if save_state:
            self.media_reader.state.save()
        if save_settings:
            self.settings.save()

        if not keep_settings:
            self.settings = Settings()
            if set_settings:
                self.setup_settings()

        _servers = list(self.default_server_list)
        if self.real:
            _servers = [s for s in SERVERS if s not in LOCAL_SERVERS]
            if ENABLED_SERVERS:
                self.settings.set_field("enabled_servers", ENABLED_SERVERS.split(","))
            if DISABLED_SERVERS:
                self.settings.set_field("disabled_servers", DISABLED_SERVERS.split(","))

        state = State(self.settings)
        _servers.sort(key=lambda x: x.id or "")
        self.media_reader = cls(state=state, server_list=_servers) if self.real else cls(state=state, server_list=_servers, tracker_list=TEST_TRACKERS)
        if not self.settings.disabled_servers and self.real:
            assert(self.media_reader.get_servers())

    def for_each(self, func, media_list, raiseException=True):
        Job(self.settings.threads, [lambda x=media_data: func(x) for media_data in media_list], raiseException=raiseException).run()

    def for_each_server(self, func):
        self.for_each(func, self.media_reader.get_servers())

    def setup_settings(self):
        self.settings.no_save_session = True
        self.settings.no_load_session = True
        self.settings.password_manager_enabled = True
        self.settings.password_load_cmd = r"echo -e a\\tb"
        self.settings.password_save_cmd = r"cat - >/dev/null"
        self.settings.shell = True
        if not self.real or SINGLE_THREADED:
            self.settings.threads = 0
        else:
            self.settings.threads = len(SERVERS)
        self.settings.fallback_to_insecure_connection = True
        self.settings.always_use_cloudscraper = False

        self.settings.max_retries = 2
        self.settings.backoff_factor = 1

        self.settings.suppress_cmd_output = True
        self.settings.viewer = "for m in {media}; do echo $m; done | sort | uniq -d | [ 0 -eq $(wc -l) ]"
        self.settings._specific_settings = {}
        self.settings.post_process_cmd = ""
        self.settings.tmp_dir = TEST_HOME + ".tmp"

        self.settings.torrent_list_cmd = "exit 0"
        self.settings.torrent_download_cmd = "exit 0"
        self.settings.torrent_stream_cmd = "exit 0"
        self.settings.torrent_info_cmd = "exit 0"

    def setUp(self):
        # Clear all env variables
        for k in set(os.environ.keys()):
            del os.environ[k]

        os.environ["AMT_HOME"] = TEST_HOME
        init_logger(logging.INFO)
        shutil.rmtree(TEST_HOME, ignore_errors=True)
        os.makedirs(TEST_HOME)
        os.chdir(TEST_HOME)
        self.reload(set_settings=True)
        self.test_server = self.media_reader.get_server(TestServer.id)
        self.test_anime_server = self.media_reader.get_server(TestAnimeServer.id)
        assert not self.media_reader.get_media_ids()

    def tearDown(self):
        shutil.rmtree(TEST_HOME, ignore_errors=True)
        self.close_sessions()

    def add_test_media(self, server_id=None, media_type=None, no_update=False, limit=None, limit_per_server=None):
        media_list = self.media_reader.get_server(server_id).list_media() if server_id else [x for server in self.media_reader.get_servers() if not media_type or server.media_type & media_type for x in server.list_media()[:limit_per_server]]
        for media_data in media_list[:limit]:
            self.media_reader.add_media(media_data, no_update=no_update)
        assert media_list
        return media_list[:limit]

    def get_all_chapters(self, name=None, media_type=None, special=False):
        for media_data in self.media_reader.get_media(name=name, media_type=media_type):
            server = self.media_reader.get_server(media_data["server_id"])
            for chapter in media_data.get_sorted_chapters():
                if not chapter["special"] or special:
                    yield server, media_data, chapter

    def get_num_chapters(self, **kwargs):
        return len(list(self.get_all_chapters(**kwargs)))

    def verify_all_chapters_read(self, name=None, media_type=None):
        assert all(map(lambda x: x[-1]["read"], self.get_all_chapters(name=name, media_type=media_type)))

    def get_num_chapters_read(self, media_type=None):
        return sum(map(lambda x: x[-1]["read"], self.get_all_chapters(media_type=media_type)))

    def verify_download(self, media_data, chapter_data):
        server = self.media_reader.get_server(media_data["server_id"])
        self.assertTrue(server.is_fully_downloaded(media_data, chapter_data))

        dir_path = self.settings.get_chapter_dir(media_data, chapter_data, skip_create=True)
        self.assertTrue(os.path.exists(dir_path))
        files = list(filter(lambda x: x[0] != ".", os.listdir(dir_path)))
        self.assertTrue(files)
        media_type = MediaType(media_data["media_type"])

        for file_name in files:
            self.assertEqual(2, len(file_name.split(".")), f"Problem with extension of {file_name}")
            path = os.path.join(dir_path, file_name)
            if isinstance(server, TestServer) or server.is_local_server() or type(server).id is None or server.torrent:
                continue
            if media_type == MediaType.MANGA:
                with open(path, "rb") as img_file:
                    Image.open(img_file)
            elif media_type == MediaType.ANIME:
                subprocess.check_call(["ffprobe", "-loglevel", "quiet", path])

        self.assertTrue(sorted(server.get_children(media_data, chapter_data)), server.get_children(media_data, chapter_data))
        for file in server.get_children(media_data, chapter_data):
            self.assertTrue(file)
            self.assertTrue(os.path.exists(file))
            self.assertFalse(os.path.basename(file)[0] == ".")

    def verify_all_chapters_downloaded(self, **kwargs):
        for _, media_data, chapter in self.get_all_chapters(**kwargs):
            self.verify_download(media_data, chapter)

    def verify_no_chapters_downloaded(self):
        for server, media_data, chapter in self.get_all_chapters():
            self.assertFalse(server.is_fully_downloaded(media_data, chapter))

    def verify_unique_numbers(self, chapters):
        list_of_numbers = sorted([chapter_data["number"] for chapter_data in chapters.values() if not chapter_data["special"]])
        set_of_numbers = sorted(list(set(list_of_numbers)))
        self.assertEqual(set_of_numbers, list_of_numbers)
        return set_of_numbers

    def verify_no_media(self):
        self.verify_media_len(0)

    def verify_media_len(self, target_len):
        self.assertEqual(target_len, len(self.media_reader.get_media_ids()))

    def verfiy_media_chapter_data(self, media_data):
        for chapter_data in media_data["chapters"].values():
            self.assertTrue(isinstance(chapter_data, ChapterData), type(chapter_data))

    def verfiy_media_list(self, media_list=None, server=None):
        assert media_list is not None
        if media_list:
            assert isinstance(media_list, list)
            for media_data in media_list:
                self.assertTrue(isinstance(media_data, MediaData), type(media_data))
                self.verfiy_media_chapter_data(media_data)
                assert "\n" not in media_data["name"]

            if not server:
                server = self.media_reader.get_server(media_list[0]["server_id"])
            assert all([x["server_id"] == server.id for x in media_list])
            assert all([x["media_type"] & server.media_type for x in media_list])

    def skip_if_all_servers_are_not_enabled(self):
        if self.settings.enabled_servers or self.settings.disabled_servers:
            self.skipTest("Server not enabled")

    def assert_server_enabled_or_skip_test(self, obj):
        if (self.settings.enabled_servers or self.settings.disabled_servers) and not obj:
            self.skipTest("Server not enabled")
        assert obj


class CliUnitTestClass(BaseUnitTestClass):
    def init(self):
        self.cli = True
        self.default_server_list = list(TEST_SERVERS) + list(LOCAL_SERVERS)


@unittest.skipIf(QUICK_TEST, "Real servers are disabled")
class RealBaseUnitTestClass(BaseUnitTestClass):
    def init(self):
        self.real = True


class UtilTest(BaseUnitTestClass):
    def test_media_type(self):
        for media_type in list(MediaType):
            self.assertEqual(media_type, MediaType.get(media_type.name))
        self.assertEqual(MediaType.MANGA, MediaType.get("bad_name", MediaType.MANGA))

    def test_get_alt_names_ignore_common_prefix(self):
        from ..util.name_parser import get_alt_names
        name_base = "Brown Fox"
        for common_prefix in ("A", "The", "That"):
            self.assertFalse(common_prefix in get_alt_names(f"{common_prefix} {name_base}"), common_prefix)

    def test_get_number_from_file_name(self):
        from ..util.name_parser import get_number_from_file_name
        name_chapter_number_pairs = [
            ("A.B.C.S01E00.1080p.BluRay.AAC2.0.x264-DEADBEEF.mkv", 0),
            ("A.B.C.S01E01.1080p.BluRay.AAC2.0.x264-DEADBEEF.mkv", 1),
            ("A B C S01E02 1080p BluRay.AAC2.0.x264-DEADBEEF.mkv", 2),
            ("A B C 03 1080p BluRay.AAC2.0.x264-DEADBEEF.mkv", 3),
            ("04. A B C 1080p BluRay.AAC2.0.x264-DEADBEEF.mkv", 4),
            ("A B C 1080p BluRay.AAC2.0.x264-DEADBEEF - 05.mkv", 5),
        ]
        for name, chapter_number in name_chapter_number_pairs:
            with self.subTest(name=name):
                self.assertEqual(get_number_from_file_name(name), chapter_number)

    def test_get_alt_names_remove_dub(self):
        from ..util.name_parser import get_alt_names
        suffixes = ["(Dub)", "(Dubbed)", "(English Dub)", "(Spanish Dub)"]
        for suffix in suffixes:
            name = "Media"
            title = name + " " + suffix
            self.assertEqual(list(get_alt_names(title)), [name])
            self.assertEqual(list(get_alt_names(title.lower())), [name.lower()])
            self.assertEqual(list(get_alt_names(title.upper())), [name.upper()])


@unittest.skipIf(not HAS_PIL, "PIL is needed to test")
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
        img = Image.new("RGB", (101, 93))
        final_img = GenericDecoder.solve_image(img, W=29, H=21)
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
        img = Image.new("RGB", (108, 72))
        for i in range(1000):
            self.assertTrue(GenericDecoder.solve_image(img, key="key", branch_factor=1, W=29, H=21))


class SettingsTest(BaseUnitTestClass):

    def test_settings_save_load(self):
        self.reload()
        for i in range(2):
            self.settings.save()
            self.settings.load()
            for field in Settings.get_members():
                self.assertEqual(self.settings.get_field(field), getattr(Settings, field), field)

    def test_settings_load_unknown_value(self):

        self.settings.save()
        future_key = "future_key"
        data = {future_key: True}
        with open(self.settings.get_settings_file(), "w") as f:
            json.dump(data, f)
        self.reload()
        self.assertFalse(self.settings.get_field(future_key))

    def test_settings_save_load_new_value(self):
        self.settings.set_field("password_save_cmd", "dummy_cmd")
        self.settings.set_field("password_save_cmd", "dummy_cmd2", TestServer.id)
        self.settings.save()
        self.assertEqual(Settings().get_field("password_save_cmd"), "dummy_cmd")
        self.assertEqual(Settings().get_field("password_save_cmd", TestServer.id), "dummy_cmd2")

    def test_settings_env_override(self):
        self.settings.load()
        for zero in (False, True):
            values = {}
            env = set()
            for key in Settings.get_members():
                if key in ("env_override_prefix", "allow_env_override", "search_score"):
                    continue
                e_key = f"AMT_{key.upper()}"
                if e_key not in os.environ and not isinstance(self.settings.get_field(key), list):
                    env.add(e_key)
                    os.environ[e_key] = str(self.settings.get_field(key)) if not zero else "0"
                    values[key] = self.settings.get_field(key)

            self.settings.load()
            for key in Settings.get_members():
                if key in ("env", "env_list"):
                    continue
                if key in values:
                    if zero:
                        self.assertFalse(self.settings.get_field(key))
                    else:
                        self.assertEqual(self.settings.get_field(key), values[key])
            if key in e_key:
                del os.environ[key]

        key = "AMT_STATUS_TO_RETRY"
        os.environ[key] = "1,2,3"
        self.settings.load()
        self.assertEqual(self.settings.status_to_retry, [1, 2, 3])

    def test_settings_env_inject(self):
        KEY, VALUE = "SOME_ARBITRARY_TEST_KEY", "123"
        self.settings.env = {KEY: VALUE}
        self.settings.save()
        self.settings.load()
        self.assertTrue(self.settings.run_cmd(f"[ ${KEY} -eq {VALUE} ]"))

    def test_set_settings_server_specific_with_env_overload(self):
        self.settings.allow_env_override = True
        self.settings.viewer = Settings.viewer
        self.settings._specific_settings = Settings._specific_settings
        target_value_manga, target_value_anime = "target_manga", "target_anime"
        os.environ["AMT_VIEWER_" + str(MediaType.MANGA)] = target_value_manga
        os.environ["AMT_VIEWER_" + str(MediaType.ANIME)] = target_value_anime
        self.settings.load()
        self.assertEqual(target_value_manga, self.settings.get_field("viewer", MediaType.MANGA.name))
        self.assertEqual(target_value_anime, self.settings.get_field("viewer", MediaType.ANIME.name))


class SettingsCredentialsTest(BaseUnitTestClass):

    def setUp(self):
        super().setUp()
        self.settings.password_load_cmd = f"cat {TEST_HOME}{{server_id}} 2>/dev/null"
        self.settings.password_save_cmd = f"( echo {{username}}; cat - ) > {TEST_HOME}{{server_id}}"

    @patch("builtins.input", return_value="0")
    @patch("getpass.getpass", return_value="1")
    def test_settings_env_override_ask_credentials(self, _username, _password):
        os.environ["AMT_PASSWORD_LOAD_CMD"] = ""
        self.settings.load()
        self.assertEqual(("0", "1"), self.media_reader.settings.get_credentials(TestServerLogin.id))

    def test_credentials(self):
        server_id = "test"
        self.assertRaises(CalledProcessError, self.settings.get_credentials, server_id)
        username, password = "user", "pass"
        self.settings.store_credentials(server_id, username, password)
        self.assertEqual((username, password), self.settings.get_credentials(server_id))
        tracker_id = "test-tracker"
        self.assertRaises(CalledProcessError, self.settings.get_credentials, tracker_id)
        self.assertRaises(CalledProcessError, self.settings.get_secret, tracker_id)
        secret = "MySecret"
        self.settings.store_secret(tracker_id, secret)
        assert secret == self.settings.get_secret(tracker_id)

    def test_credentials_override(self):
        self.settings.password_override_prefix = "prefix"
        server_id = "test"
        username, password = "user", "pass"
        for sep in ("\n", "\t"):
            with self.subTest(sep=sep):
                os.environ[self.settings.password_override_prefix + server_id] = f"{username}{sep}{password}"
                try:
                    self.assertEqual(username, self.settings.get_credentials(server_id)[0])
                    self.assertEqual(password, self.settings.get_credentials(server_id)[1])
                    self.assertRaises(CalledProcessError, self.settings.get_credentials, "bad_id")
                finally:
                    del os.environ[self.settings.password_override_prefix + server_id]


class ServerWorkflowsTest(BaseUnitTestClass):

    def test_session_get_post_with_ssl_error(self):
        def fake_request(*args, **kwargs):
            if kwargs.get("verify", True):
                raise requests.exceptions.SSLError()
            r = requests.Response()
            r.status_code = 200
            return r
        self.test_server.session.get = fake_request
        self.test_server.session.post = self.test_server.session.get

        self.settings.fallback_to_insecure_connection = False
        self.settings.disable_ssl_verification = False
        self.assertRaises(requests.exceptions.SSLError, self.test_server.session_get, "some_url")
        self.assertRaises(requests.exceptions.SSLError, self.test_server.session_post, "some_url")
        for fallback, disable in ((True, False), (False, True)):
            self.settings.fallback_to_insecure_connection = fallback
            self.settings.disable_ssl_verification = disable
            self.assertTrue(self.test_server.session_get("some_url"))
            self.assertTrue(self.test_server.session_post("some_url"))

    def test_session_cache(self):
        def fake_request(*args, **kwargs):
            r = requests.Response()
            r.status_code = 200
            return r

        get = self.test_server.session.get
        self.test_server.session.get = self.test_anime_server.session.get = fake_request

        self.test_server.session_get_cache("some_url", mem_cache=False)
        self.test_anime_server.session_get_cache("some_url", mem_cache=True)

        self.test_server.session.get = self.test_anime_server.session.get = get

        self.test_server.session_get_cache("some_url", mem_cache=False)
        self.test_anime_server.session_get_cache("some_url", mem_cache=True)

    def test_session_permanent_ssl_error(self):
        def fake_request(*args, **kwargs):
            raise requests.exceptions.SSLError()
        self.test_server.session.get = fake_request
        self.settings.fallback_to_insecure_connection = True
        self.assertRaises(requests.exceptions.SSLError, self.test_server.session_get, "some_url")

    def test_session_get_post_with_connection_error(self):
        self.counter = 0

        def fake_request(*args, **kwargs):
            self.counter = self.counter + 1
            if self.counter % 2 == 1:
                raise requests.exceptions.ConnectionError()
            r = requests.Response()
            r.status_code = 200
            return r

        def fake_request_err(*args, **kwargs):
            raise requests.exceptions.ConnectionError()
        self.test_server.session.get = fake_request_err
        self.assertRaises(requests.exceptions.ConnectionError, self.test_server.session_get, "some_url")
        self.test_server.session.get = fake_request
        self.test_server.session.post = self.test_server.session.get
        self.test_server.session_get("some_url")
        self.test_server.session_post("some_url")

    def test_session_get_post_with_failed_http_status(self):
        self.media_reader.settings.status_to_retry = [429]
        self.media_reader.settings.max_retries = 2
        self.media_reader.settings.backoff_factor = .01
        always_fail = False
        self.counter = 0

        def fake_request(*args, **kwargs):
            self.counter = self.counter + 1
            r = requests.Response()
            r.status_code = 429 if always_fail or self.counter % 2 == 1 else 200
            return r
        self.test_server.session.get = fake_request
        self.test_server.session.post = fake_request
        self.test_server.session_get("some_url")
        self.test_server.session_post("some_url")
        always_fail = True
        self.assertRaises(requests.exceptions.HTTPError, self.test_server.session_get, "some_url")

    def test_session_maybe_need_cloud_scraper(self):
        def return_403_response(*args, **kwargs):
            r = requests.Response()
            r.status_code = 403
            return r

        def return_200_response(*args, **kwargs):
            r = requests.Response()
            r.status_code = 200
            return r
        try:
            self.test_server.session.get = return_403_response
            RequestServer.cloudscraper = requests.Session()
            RequestServer.cloudscraper.get = return_200_response
            self.test_server.maybe_need_cloud_scraper = True
            self.test_server.session_get("test")
        except ImportError:
            self.skipTest("cloudscraper not installed")

    def test_session_get_cache_json(self):
        server = self.media_reader.get_server(TestServer.id)
        assert server
        url = "https://dummy_url"
        os.makedirs(self.settings.get_web_cache_dir(), exist_ok=True)
        file = self.settings.get_web_cache(url)
        data = [0, 1, 0]
        with open(file, "w") as f:
            json.dump(data, f)
        self.assertEqual(data, server.session_get_cache_json(url))
        self.assertEqual(json.dumps(data), server.session_get_cache(url))
        self.assertEqual(json.dumps(data), server.session_get_cache(url))
        server.session_get_cache(url, ttl=0)
        self.assertFalse(os.path.exists(file))
        self.assertNotEqual(json.dumps(data), server.session_get_cache(url))

    def test_skip_servers_that_cannot_be_imported(self):
        with patch.dict(sys.modules, {"amt.tests.test_server": None}):
            remaining_servers = import_sub_classes(tests, TestServer)
            self.assertNotEqual(remaining_servers, TEST_SERVERS)

    def test_force_cloudfare(self):
        try:
            self.settings.set_field("always_use_cloudscraper", True, TestServer.id)
            server = TestServer(self.media_reader.session, self.settings, no_fake_session=True)
            server2 = TestAnimeServer(self.media_reader.session, self.settings, no_fake_session=True)
            self.assertNotEqual(server.session, self.media_reader.session)
            self.assertEqual(server2.session, self.media_reader.session)
        except ImportError:
            self.skipTest("cloudscraper not installed")

    def test_media_reader_add_remove_media(self):
        for server in self.media_reader.get_servers():
            with self.subTest(server=server.id):
                media_list = server.list_media()
                assert media_list
                selected_media = media_list[0]
                self.media_reader.add_media(selected_media)
                my_media_id_list = list(self.media_reader.get_media_ids())
                self.assertEqual(1, len(my_media_id_list))
                self.assertEqual(my_media_id_list[0], selected_media.global_id)
                self.media_reader.remove_media(name=selected_media)
                self.verify_no_media()

    def test_server_download(self):
        for server in self.media_reader.get_servers():
            for media_data in server.list_media():
                with self.subTest(server=server.id, media_data=media_data["name"]):
                    server.update_media_data(media_data)
                    for stream_index, chapter_data in zip((0, -1), media_data.get_sorted_chapters()[0:2]):
                        self.assertEqual(True, server.download_chapter(media_data, chapter_data, page_limit=2, stream_index=stream_index))
                        self.verify_download(media_data, chapter_data)

    def test_server_download_errors(self):
        errors = (ChapterLimitException(time.time() * 3600, 100), ValueError())
        for error, media_data in zip(errors, self.add_test_media(server_id=TestServer.id, limit=2)):
            self.test_server.inject_error(delay=1, error=error)
            self.assertRaises(type(error), self.media_reader.download_unread_chapters, media_data)
            self.media_reader.download_unread_chapters(media_data)
            self.verify_all_chapters_downloaded(name=media_data)

    def test_server_download_post_process_fail(self):
        self.settings.post_process_cmd = "exit 1"
        media_data = self.add_test_media(server_id=TestServer.id, limit=1)[0]
        self.media_reader.download_unread_chapters(media_data)

    def test_search_media(self):
        for server in self.media_reader.get_servers():
            with self.subTest(server=server.id):
                media_data = server.list_media()[0]
                name = media_data["name"]
                self.assertEqual(media_data, list(server.search(name))[0][1])
                assert server.search(name[:3])

    def test_search_inexact(self):
        self.assertTrue(self.test_server.search("The Manga1"))
        self.assertTrue(self.test_server.search("Manga1: the second coming"))
        self.assertTrue(self.test_server.search("Manga"))

    def login_test_helper(self, expected_exception=ValueError):
        self.add_test_media(TestServerLogin.id)
        self.assertRaises(expected_exception, self.media_reader.download_unread_chapters)

    def test_login_non_premium_account(self):
        self.media_reader.get_server(TestServerLogin.id).premium_account = False
        self.login_test_helper()

    def test_error_on_login(self):
        self.media_reader.get_server(TestServerLogin.id).error_login = True
        self.login_test_helper()

    def test_relogin_fail_to_load_credentials(self):
        self.settings.password_load_cmd = "exit 1"
        self.login_test_helper(CalledProcessError)

    def test_relogin_on_mature_content(self):
        server = self.media_reader.get_server(TestServerLoginAnime.id)
        media_list = self.add_test_media(server.id)
        for media_data in media_list:
            server.reset()
            self.media_reader.download_unread_chapters(media_data)

    def test_missing_m3u8(self):
        server = self.media_reader.get_server(TestAnimeServer.id)
        self.add_test_media(server.id, media_type=MediaType.ANIME, limit=1)
        with patch.dict(sys.modules, {"m3u8": None}):
            server.stream_urls = [["dummy.m3u8"]]
            self.assertRaises(ImportError, self.media_reader.download_unread_chapters)
            self.verify_no_chapters_downloaded()
            server.stream_urls = [["dummy.m3u8", "dummy.mp4"]]
            self.media_reader.download_unread_chapters()
            self.verify_all_chapters_downloaded()

    def test_unique_download_paths(self):
        self.add_test_media()
        paths = {self.settings.get_chapter_dir(media_data, chapter_data) for _, media_data, chapter_data in self.get_all_chapters()}
        self.assertEqual(len(paths), len(list(self.get_all_chapters())))


class MediaReaderTest(BaseUnitTestClass):
    def test_add_remove(self):
        media_data = self.add_test_media(server_id=TestServer.id, limit=1)[0]
        self.verify_media_len(1)
        self.assertRaises(ValueError, self.media_reader.add_media, media_data)
        self.verify_media_len(1)
        self.media_reader.remove_media(name=media_data)
        self.assertRaises(KeyError, self.media_reader.remove_media, name=media_data)

    def test_add_remove_remember(self):
        media_data = self.add_test_media(server_id=TestServer.id, limit=1)[0]
        self.media_reader.mark_read()
        self.media_reader.state.save()
        self.reload()
        self.media_reader.remove_media(name=media_data.global_id)
        media_data = self.add_test_media(server_id=TestServer.id, limit=1)[0]
        self.verify_all_chapters_read(name=media_data)

    def test_load_servers(self):
        self.assertEqual(len(TEST_SERVERS), len(self.media_reader.state.get_server_ids()))
        self.assertEqual(len(TEST_TRACKERS), len(self.media_reader.get_tracker_ids()))

    def test_failed_instantiation(self):
        class FakeServer(TestServer):
            id = "fakeServerId"

            def __init__(self, *args, **kwargs):
                raise ImportError("explicitly thrown error")
        self.default_server_list = [FakeServer]
        self.reload()
        self.assertTrue(FakeServer.id not in self.media_reader.state.get_server_ids())

    def test_select_servers(self):
        server_ids = list(self.media_reader.state.get_server_ids())
        self.settings.disabled_servers = server_ids
        self.reload(save_settings=True)
        self.assertFalse(self.media_reader.state.get_server_ids())
        self.settings.disabled_servers = server_ids[1:]
        self.reload(save_settings=True)
        self.assertEqual(server_ids[:1], list(self.media_reader.state.get_server_ids()))
        self.settings.enabled_servers = server_ids[-1:]
        self.reload(save_settings=True)
        self.assertEqual(server_ids[-1:], list(self.media_reader.state.get_server_ids()))

    def test_disable_unofficial_servers(self):
        self.add_test_media()

        for i in range(2):
            self.assertFalse(all(map(lambda x: self.media_reader.get_server(x["server_id"]).official, self.media_reader.get_media())))
            self.media_reader.settings.allow_only_official_servers = True
            self.media_reader.mark_read()
            self.verify_all_chapters_read()

            self.reload(save_settings=True, save_state=True)
            self.assertTrue(self.media_reader.settings.allow_only_official_servers)
            self.assertTrue(self.media_reader.get_media_ids())
            self.assertTrue(all(map(lambda x: self.media_reader.get_server(x["server_id"]).official, self.media_reader.get_media())))
            self.media_reader.settings.allow_only_official_servers = False
            self.verify_all_chapters_read()

            self.reload(save_settings=True, save_state=True)
            self.media_reader.update()
            self.verify_all_chapters_read()

    def test_load_cookies_session_cookies(self):
        self.media_reader.settings.no_load_session = False
        values = ["1", "too", "three"]
        name, name2 = "Test", "Test2"
        self.settings.cookie_files = []
        os.makedirs(self.settings.cache_dir, exist_ok=True)
        with open(self.settings.get_cookie_file(), "w") as f:
            f.write("\t".join([self.test_server.id, "TRUE", "/", "FALSE", "1640849596", name, values[0], "None"]))
            f.write("\n")
            f.write("#Comment\n")
            f.write("\t".join([self.test_server.id, "TRUE", "/", "FALSE", "1640849596", name2, values[1], "None"]))
            f.write("\n")
            f.write("\t".join([self.test_anime_server.id, "TRUE", "/", "FALSE", "1640849596", name, values[2], "None"]))

        self.media_reader.state.load_session_cookies()
        assert self.media_reader.session.cookies
        self.assertEqual(values[0], self.test_server.session_get_cookie(name))
        self.assertEqual(values[1], self.test_server.session_get_cookie(name2))
        self.assertEqual(values[2], self.test_anime_server.session_get_cookie(name))

    def test_save_load_cookies(self):
        self.media_reader.settings.no_load_session = False
        self.media_reader.settings.no_save_session = False
        key, value = "Test", "value"
        self.media_reader.session.cookies.set(key, value)
        assert self.media_reader.state.save_session_cookies()
        self.media_reader.session.cookies.set(key, "bad_value")
        self.media_reader.state.load_session_cookies()
        self.assertEqual(value, self.media_reader.session.cookies.get(key))
        self.media_reader.session.cookies.set(key, "bad_value")
        self.media_reader.state.load_session_cookies()
        assert not self.media_reader.state.save_session_cookies()

    def test_save_load(self):
        assert not os.path.exists(self.settings.get_metadata_file())
        self.add_test_media(TestServer.id)
        old_hash = State.get_hash(self.media_reader.media)
        self.media_reader.state.save()
        assert os.path.exists(self.settings.get_metadata_file())
        self.reload()
        self.assertEqual(old_hash, State.get_hash(self.media_reader.media))
        for media_data in self.media_reader.get_media():
            self.assertTrue(media_data["chapters"])
            self.assertTrue(media_data.chapters)

    def test_save_load_global_id_format_change(self):
        self.add_test_media(TestServer.id)
        original_keys = set(self.media_reader.media.keys())
        for key in original_keys:
            self.media_reader.media["old_" + key] = self.media_reader.media[key]
            del self.media_reader.media[key]
        self.media_reader.state.save()
        self.reload()
        self.assertEqual(original_keys, set(self.media_reader.media.keys()))

    def test_save_load_disabled(self):
        self.add_test_media()
        old_hash = State.get_hash(self.media_reader.media)
        self.media_reader.state.save()
        self.media_reader.state.configure_media({})
        assert not self.media_reader.media
        self.media_reader.state.save()
        self.media_reader.state.configure_media({s.id: s for s in self.media_reader.get_servers()})
        assert self.media_reader.media
        self.assertEqual(old_hash, State.get_hash(self.media_reader.media))

    def test_empty_chapter_metadata(self):
        media_data = self.add_test_media(TestServer.id, limit=1)[0]
        self.media_reader.state.save()
        media_data["chapters"].clear()
        self.media_reader.state.save()
        self.reload()

    def test_mark_chapters_until_n_as_read(self):
        media_data = self.add_test_media(server_id=TestServer.id, limit=1)[0]
        assert len(media_data["chapters"]) > 2
        last_chapter_num = max(media_data["chapters"].values(), key=lambda x: x["number"])["number"]
        last_chapter_num_read = last_chapter_num - 1
        assert last_chapter_num > 1
        self.media_reader.mark_chapters_until_n_as_read(media_data, last_chapter_num_read)

        assert all(map(lambda x: x["read"], filter(lambda x: last_chapter_num_read >= x["number"], media_data["chapters"].values())))

    def test_download_unread_chapters(self):
        self.add_test_media(TestServer.id)
        count = self.media_reader.download_unread_chapters()
        self.assertEqual(count, self.get_num_chapters())
        self.verify_all_chapters_downloaded()

    def test_update_no_media(self):
        assert not self.media_reader.update()

    def test_update(self):
        media_data = self.add_test_media(server_id=TestServer.id, no_update=True)[0]
        num_new_chapters = self.media_reader.update_media(media_data)
        self.assertTrue(num_new_chapters)
        self.assertFalse(self.media_reader.update_media(media_data))
        media_data["chapters"].clear()
        num_new_chapters2 = self.media_reader.update_media(media_data)
        self.assertEqual(num_new_chapters, num_new_chapters2)

    def test_update_keep_removed(self):
        fake_chapter_id = "fakeId"
        media_list = self.add_test_media()
        original_len = len(media_list[0]["chapters"])
        media_list[0]["chapters"][fake_chapter_id] = ChapterData(list(media_list[0]["chapters"].values())[0])
        self.media_reader.mark_read()
        self.settings.keep_unavailable = True
        self.media_reader.update()
        self.assertTrue(fake_chapter_id in media_list[0]["chapters"])
        self.settings.keep_unavailable = False
        self.media_reader.update()
        self.assertFalse(fake_chapter_id in media_list[0]["chapters"])
        self.assertEqual(original_len, len(media_list[0]["chapters"]))
        self.verify_all_chapters_read()

    def test_preserve_read_status_on_update(self):
        media_list = self.add_test_media()
        self.media_reader.mark_read()
        for i in range(2):
            for media_data in media_list:
                assert all(map(lambda x: x["read"], media_data["chapters"].values()))
            self.media_reader.update()

    def test_sync_with_no_chapters(self):
        self.add_test_media(TestServer.id, no_update=True)
        self.media_reader.sync_progress()

    def test_sync_untracked(self):
        media_list = self.add_test_media(TestServer.id)
        self.media_reader.mark_read()
        self.media_reader.sync_progress()
        self.assertFalse(any(map(lambda x: x["progress"], media_list)))

    def test_mark_read(self):
        media_list = self.add_test_media(TestServer.id, no_update=True)
        self.media_reader.mark_read(self.test_server.id)
        self.media_reader.update()
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

    def test_stream_anime_bad_url(self):
        assert not self.media_reader.stream("bad_url")

    def test_stream_anime_cont(self):
        self.assertTrue(self.media_reader.stream(TestAnimeServer.get_streamable_url(), cont=True) > 1)

    def test_stream_anime_redirect(self):
        self.assertEqual(self.media_reader.get_server_for_url(TestAnimeServer.get_redirectable_url(), server_id=TestAnimeServer.id)[1].id, TestAnimeServer.id)

    def test_stream_anime_manga(self):
        self.assertTrue(self.media_reader.stream(TestServer.get_streamable_url()))

    def test_play_anime(self):
        self.add_test_media(media_type=MediaType.ANIME)
        self.assertTrue(self.media_reader.play(limit=None))
        self.verify_all_chapters_read()

    def test_play_anime_limit(self):
        self.add_test_media(media_type=MediaType.ANIME)
        self.assertTrue(self.media_reader.play(limit=1))
        self.assertEqual(1, self.get_num_chapters_read())

    def test_play_batch_size_use_first_chapter_for_env(self):
        media_data = next(filter(lambda x: len(x["chapters"]) > 3, self.add_test_media(media_type=MediaType.MANGA)))
        chapters = media_data.get_sorted_chapters()
        self.settings.viewer = f'[ "$CHAPTER_NUMBER" != {chapters[1]["number"]} ]'
        self.assertTrue(self.media_reader.play(media_data, batch_size=2, limit=3))
        self.assertEqual(self.get_num_chapters_read(), 3)

    def test_play_no_batch_size(self):
        self.add_test_media(media_type=MediaType.MANGA)
        self.settings.viewer = 'for m in {media}; do dirname "$m"; done | sort | uniq | [ $(wc -l) -eq 1 ]'
        self.media_reader.play()
        self.verify_all_chapters_read()

    def test_play_batch_size(self):
        self.add_test_media(media_type=MediaType.MANGA)
        self.settings.viewer = 'for m in {media}; do dirname "$m"; done | sort | uniq | [ $(wc -l) -le 2 ]'
        self.media_reader.play(batch_size=2)
        self.verify_all_chapters_read()

    def test_play_verify_subtitles_batch_size(self):
        self.add_test_media(TestAnimeServer.id)
        self.settings.viewer = 'set -e; [ -n "$SUB_PATH" ]; IFS=:; for path in $SUB_PATH; do [ -d $path ]; done;'
        self.assertTrue(self.media_reader.play(batch_size=2))
        self.verify_all_chapters_read()

    def test_play_offset_anime(self):
        media_data = self.add_test_media(media_type=MediaType.ANIME, limit=1)[0]
        chapters = media_data.get_sorted_chapters()
        max_num = chapters[-1]["number"]
        min_num = chapters[0]["number"]
        self.media_reader.offset(media_data, 1)
        self.assertEqual(max_num, chapters[-1]["number"] + 1)
        self.assertEqual(min_num, chapters[0]["number"] + 1)

    def test_play_anime_downloaded(self):
        self.add_test_media(media_type=MediaType.ANIME, limit=1)
        self.media_reader.download_unread_chapters()
        self.verify_all_chapters_downloaded()
        self.assertTrue(self.media_reader.play(limit=1))

    def test_get_media(self):
        self.add_test_media()
        for name in self.media_reader.state.get_all_names():
            self.assertTrue(self.media_reader.get_single_media(name=name))

    def test_get_media_tag(self):
        media_list = self.add_test_media()
        media_data = media_list[0]
        tag_name, tag_name2 = "test", "test2"
        self.assertFalse(list(self.media_reader.get_media(tag=tag_name)))
        self.media_reader.tag(name=media_data, tag_name=tag_name)
        self.assertEqual(1, len(list(self.media_reader.get_media(tag=tag_name))))
        self.assertEqual(1, len(list(self.media_reader.get_media(tag=""))))
        self.media_reader.tag(None, tag_name=tag_name2)
        self.assertEqual(1, len(list(self.media_reader.get_media(tag=tag_name))))
        self.assertEqual(len(media_list), len(list(self.media_reader.get_media(tag=tag_name2))))
        self.assertEqual(len(media_list), len(list(self.media_reader.get_media(tag=""))))
        self.media_reader.untag(None, tag_name=tag_name)
        self.assertEqual(len(media_list), len(list(self.media_reader.get_media(tag=""))))
        self.media_reader.untag(None, tag_name=tag_name2)
        self.assertEqual(0, len(list(self.media_reader.get_media(tag=""))))

    def test_search_add(self):
        media_data = self.media_reader.search_add("a")
        assert(media_data)
        assert media_data in list(self.media_reader.get_media())

    def test_load_from_tracker(self):
        n = self.media_reader.load_from_tracker(1)
        self.assertTrue(n)
        self.assertEqual(n, len(self.media_reader.get_media_ids()))
        self.assertEqual(0, self.media_reader.load_from_tracker(1))

    def test_play_with_env_list(self):
        self.add_test_media(server_id=TestServer.id, limit=1)

        KEY, VALUE1, VALUE2 = "SOME_ARBITRARY_TEST_KEY", "1", "2"
        self.settings.set_field("env_list", {KEY: VALUE2})
        self.settings.set_field("env_list", {KEY: VALUE1}, TestServer.id)
        self.settings.viewer = f'[ "${KEY}" = "{VALUE1} {VALUE2}" ]'
        self.assertTrue(self.media_reader.play(limit=1))

        VALUE3 = "3"
        self.settings.set_field("env", {KEY: VALUE3})
        self.settings.viewer = f'[ "${KEY}" = "{VALUE3}" ]'
        self.assertTrue(self.media_reader.play())


class ApplicationTestWithErrors(CliUnitTestClass):
    def setUp(self):
        super().setUp()
        self.media_reader.auto_select = True

    def test_search_with_error(self):
        self.test_server.inject_error()
        assert self.media_reader.search_add("manga")
        assert self.test_server.was_error_thrown()

    def test_update_with_error(self):
        media_list = self.add_test_media(no_update=True)
        self.test_server.inject_error()
        self.assertRaises(ValueError, parse_args, media_reader=self.media_reader, args=["update"])
        assert self.test_server.was_error_thrown()
        self.reload()
        self.assertEqual(len(media_list), len(self.media_reader.get_media_ids()))

    def test_download_with_error(self):
        self.add_test_media()
        self.test_server.inject_error()
        self.assertRaises(ValueError, self.media_reader.download_unread_chapters)
        assert self.test_server.was_error_thrown()

    def test_download_with_retry(self):
        self.add_test_media(TestServer.id, limit=1)
        self.test_server.inject_error(RetryException("Dummy Retry"))
        assert self.media_reader.download_unread_chapters()
        assert self.test_server.was_error_thrown()
        self.verify_all_chapters_downloaded()

    def test_download_with_repeated_failures(self):
        self.add_test_media(TestServer.id, limit=1)
        self.test_server.inject_error(RetryException(None, "Dummy Retry"), -1)
        self.assertRaises(RetryException, self.media_reader.download_unread_chapters)

    def test_download_with_retry_multithreaded(self):
        self.media_reader.settings.threads = 1
        self.add_test_media(TestServer.id, limit=1)
        self.test_server.inject_error(RetryException(None, "Dummy Retry"))
        assert self.media_reader.download_unread_chapters()
        assert self.test_server.was_error_thrown()
        self.verify_all_chapters_downloaded()


class GenericServerTest():
    def _test_list_and_search(self, server, test_just_list=False, media_type=None):
        media_list = None
        with self.subTest(server=server.id, list=True):
            media_list = server.list_media(limit=4, media_type=media_type)
            assert media_list or not server.has_free_chapters or not server.domain
            self.verfiy_media_list(media_list, server=server)

        if media_list and not test_just_list:
            with self.subTest(server=server.id, list=False):
                for N in (1, 10):
                    search_media_list = server.search(media_list[0]["name"], limit=N, media_type=media_type) or server.search(media_list[0]["name"].split()[0], limit=N, media_type=media_type)
                    if search_media_list:
                        break
                assert search_media_list
                self.verfiy_media_list(media_list, server=server)
        return media_list

    def test_future_proof_get_media_list(self):
        def fake_request(*args, **kwargs):
            raise ValueError("Expected")
        for server in self.media_reader.get_servers():
            server._request = fake_request
            with self.subTest(server=server.id):
                try:
                    server.get_media_list(unknown_kwargs=0)
                except ValueError:
                    pass
                try:
                    # Normally this method should be treated as private
                    server.search_for_media("term", unknown_kwargs=0)
                except ValueError:
                    pass

    def test_workflow(self):
        def test_list_search_download(server, media_type):
            for media_data in self._test_list_and_search(server, media_type=media_type):
                if media_type and server.official:
                    self.assertTrue(media_data["media_type"] & media_type)
                elif media_data.global_id in self.media_reader.get_media_ids():
                    continue
                self.media_reader.add_media(media_data)
                self.verfiy_media_chapter_data(media_data)
                if server.torrent and not media_data["chapters"]:
                    break
                for chapter_data in filter(lambda x: not x["premium"], media_data.get_sorted_chapters()):
                    if not SKIP_DOWNLOAD and not server.slow_download:
                        self.assertNotEqual(server.is_local_server(), server.download_chapter(media_data, chapter_data, page_limit=2))
                        self.verify_download(media_data, chapter_data)
                        assert not server.download_chapter(media_data, chapter_data, page_limit=1)
                    return True
                if not server.torrent:
                    self.assertTrue(server.id in self.media_reader.state.get_server_ids_with_logins())

        def func(server):
            with self.subTest(server=server.id):
                if server.need_to_login_to_list:
                    return
                for media_type in list(MediaType):
                    if server.media_type & media_type:
                        test_list_search_download(server, media_type)
        self.for_each_server(func)
        self.media_reader.state.save()

    def test_login_fail(self):
        self.media_reader.settings.password_manager_enabled = True
        self.media_reader.settings.password_load_cmd = r"echo -e A\\tB"
        self.settings.max_retries = 1
        self.reload(keep_settings=True)

        def func(server):
            try:
                with self.subTest(server=server.id, method="relogin"):
                    assert not server.relogin()
            finally:
                assert server.needs_to_login()

        unique_login_servers = {x.alias or x.id: x for x in map(self.media_reader.get_server, self.media_reader.state.get_server_ids_with_logins()) if x}
        self.for_each(func, unique_login_servers.values())


class TorrentServerTest(GenericServerTest, BaseUnitTestClass):
    torrents = ["TorrentA.torrent", "TorrentB.torrent", "TorrentC.torrent", "TorrentD.torrent"]
    torrent_files = ["1.file", "2.file", "dir/3.file", "nested/dir/4.file"]

    def setup_settings(self, **kwargs):
        super().setup_settings(**kwargs)
        self.settings.torrent_info_cmd = '[ -e "$TORRENT_FILE" ] && read -r name < "$TORRENT_FILE"; printf "Hash: %s\\nName: %s\\n" "$name" "$name"'
        self.settings.torrent_list_cmd = '[ -e "$TORRENT_FILE" ] && printf "{}"'.format('\\n'.join(self.torrent_files))
        self.settings.torrent_download_cmd = '[ -e "$TORRENT_FILE" ] && mkdir -p "$(dirname "$CHAPTER_ID")" && touch "$CHAPTER_ID"'
        self.settings.torrent_stream_cmd = '[ -e "$TORRENT_FILE" ] && [ -n "$VIEWER_CMD" ] && [ -n "$CHAPTER_ID" ] && echo 0 | sh -c "$VIEWER_CMD"'
        self.settings.viewer = '[ -z "$STREAMING" ] || ( read -r value && [ "$value" -eq 0 ]; )'

    def tearDown(self):
        for x in self.torrents:
            assert(os.path.exists(x))
        super().tearDown()

    def init(self):
        self.default_server_list = [s for s in SERVERS if s.torrent and s.domain is None]
        self.assertEqual(len(self.default_server_list), 1)

    def reload(self, **kwargs):
        super().reload(**kwargs)
        for x in self.torrents:
            with open(x, "w+") as f:
                f.write(x.split(".")[0])

        for server in self.media_reader.get_servers():
            server.get_media_list = lambda **kwargs: [server.get_media_data_from_url(x) for x in self.torrents]

    def test_media_type_selection(self):
        def func(server):
            with self.subTest(server=server.id):
                for media_data in self._test_list_and_search(server):
                    self.media_reader.add_media(media_data)
                    self.assertTrue(media_data["chapters"])
                    self.verfiy_media_chapter_data(media_data)
        self.for_each_server(func)
        self.media_reader.play()
        self.verify_all_chapters_read()
        self.verfiy_media_list(list(self.media_reader.get_media()))

    def test_add_media_from_url(self):
        for torrent in self.torrents:
            assert(self.media_reader.add_from_url(torrent))
            self.media_reader.media.clear()
            assert(self.media_reader.add_from_url(os.path.abspath(torrent)))

    def test_media_stream(self):
        for torrent, media_type in zip(self.torrents, list(MediaType)):
            with self.subTest(media_type=media_type):
                for file in self.torrent_files:
                    self.assertTrue(self.media_reader.stream(f"{torrent}?file={file}", media_type=media_type))
                    self.assertTrue(self.media_reader.stream(f"{os.path.abspath(torrent)}?file={file}"))

    def test_media_stream_torrent_dont_use_viewer_directly(self):
        self.settings.torrent_stream_cmd = '[ -e "$TORRENT_FILE" ]'
        self.settings.viewer = 'exit 1'
        for torrent in self.torrents:
            for file in self.torrent_files:
                self.assertTrue(self.media_reader.stream(f"{torrent}?file={file}", media_type=MediaType.ANIME))

    def test_download_torrent_fail(self):
        self.settings.torrent_download_cmd = 'exit 1'
        media_data = self.media_reader.add_from_url(self.torrents[0])
        self.assertTrue(media_data["chapters"])
        try:
            self.media_reader.download_unread_chapters(media_data)
        except:
            pass
        self.verify_no_chapters_downloaded()


class LocalServerTest(GenericServerTest, BaseUnitTestClass):
    def init(self):
        self.default_server_list = list(LOCAL_SERVERS)

    def setUp(self):
        super().setUp()
        self.setup_customer_server_data()

    def setup_customer_server_data(self):
        for server in self.media_reader.get_servers():
            for media_data in (server.create_media_data("A", "A"), server.create_media_data("B", "B")):
                for number, chapter_name in enumerate(["00", "01.", "2.0 Chapter Tile", "3 Chapter_Title", "4"]):
                    chapter_id = f"{chapter_name}_{number}"
                    server.update_chapter_data(media_data, id=chapter_id, title=chapter_name, number=number)
                    chapter_dir = self.settings.get_chapter_dir(media_data, media_data["chapters"][chapter_id])
                    open(os.path.join(chapter_dir, "text.xhtml"), "w").close()
                self.assertTrue(len(media_data["chapters"]) > 1, media_data["chapters"].keys())

    def test_detect_chapters(self):
        for server in self.media_reader.get_servers():
            self.media_reader.media.clear()
            with self.subTest(server=server.id):
                media_list = self.add_test_media(server_id=server.id)
                for media_data in media_list:
                    self.assertTrue(media_data["chapters"], media_data["name"])

    def test_custom_update(self):
        self.add_test_media()
        for media_data in self.media_reader.get_media():
            assert not self.media_reader.update_media(media_data)

    def test_custom_save_update(self):
        self.add_test_media()
        num_chapters = self.get_num_chapters()
        self.assertTrue(num_chapters)
        funcs = [self.media_reader.state.save, self.reload, self.media_reader.update]
        for func in funcs:
            func()
            self.assertEqual(num_chapters, self.get_num_chapters(), func)

    def test_custom_clean(self):
        self.add_test_media()
        self.media_reader.state.save()
        num_chapters = self.get_num_chapters()
        self.assertTrue(num_chapters)
        self.media_reader.mark_read()
        self.media_reader.clean(remove_read=True)
        self.media_reader.update()
        self.assertEqual(num_chapters, self.get_num_chapters())
        self.media_reader.clean(include_local_servers=True, remove_read=True)
        self.media_reader.update()
        self.assertFalse(self.get_num_chapters())
        for media_data in self.media_reader.get_media():
            self.assertTrue(os.listdir(self.settings.get_media_dir(media_data)))


class RemoteServerTest(GenericServerTest, BaseUnitTestClass):
    port = 8888
    resources_dir_name = ".resources"
    valid_domain = f"http://localhost:{port}"

    def init(self):
        self.default_server_list = [RemoteServer]

    @classmethod
    def setUpClass(cls):
        os.makedirs(TEST_TEMP)
        os.chdir(TEST_TEMP)
        cls.web_server = subprocess.Popen(["python", "-m", "http.server", str(cls.port)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        while True:
            try:
                requests.get(f"http://localhost:{cls.port}")
                break
            except ConnectionError:
                time.sleep(.01)

    @classmethod
    def tearDownClass(cls):
        cls.web_server.kill()
        cls.web_server.wait()
        shutil.rmtree(TEST_TEMP)

    file_info = (
        ("A", ["Test1/media/1/file.test", "Test1/media/2/file.test"], MediaType.ANIME, False, 1, 2),
        ("B", ["Test2/file2.test"], MediaType.MANGA, False, 1, 1),
        ("C", ["Test3 file.test"], MediaType.NOVEL, False, 1, 1),
        ("D", ["file.test"], MediaType.ANIME, True, 1, 1),
        ("E", ["TestAuth/media/1/file.test"], MediaType.ANIME, True, 1, 1),
    )

    def setUp(self):
        super().setUp()
        for path in os.listdir(TEST_TEMP):
            abs_path = os.path.join(TEST_TEMP, path)
            if os.path.isdir(abs_path):
                shutil.rmtree(os.path.join(TEST_TEMP, path))
            else:
                os.unlink(abs_path)
        os.makedirs(self.settings.config_dir)
        conf = {}
        for server_dir, relative_paths, media_type, auth, _, _ in self.file_info:
            server_id = f"{server_dir}_remote_test_{media_type.name}" + (" _auth" if auth else "")
            for path in relative_paths:
                abs_path = os.path.join(TEST_TEMP, server_dir, path)
                os.makedirs(os.path.dirname(abs_path), exist_ok=True)
                if path.count("/") > 1:
                    parent = os.path.dirname(abs_path)
                    grand_parent = os.path.dirname(parent)
                    open(os.path.join(grand_parent, self.settings.get_chapter_metadata_file_basename()), "w").close()
                    resource_path = os.path.join(parent, self.resources_dir_name, "nested")
                    os.makedirs(resource_path, exist_ok=True)
                    open(os.path.join(resource_path, "some_resource"), "w").close()
                open(abs_path, "w").close()
            conf[server_id] = {
                "domain_list": [f"http://localhost:-1{self.port}", "__bad_domain__", self.valid_domain],
                "path": server_dir
            }
            if media_type:
                conf[server_id]["media_type"] = media_type.name
            if auth:
                conf[server_id]["auth"] = True
                conf[server_id]["username"] = "admin"
                conf[server_id]["password"] = "root"
        with open(self.settings.get_remote_servers_config_file(), "w") as f:
            json.dump(conf, f)

        self.reload(True)
        if ENABLED_SERVERS and not self.media_reader.get_servers():
            self.skipTest("Server not enabled")
        self.assertEqual(len(self.media_reader.get_servers()), len(self.file_info))

    def test_add_media(self):
        media_list = self.add_test_media()
        self.assertEqual(len(media_list), sum(map(lambda x: x[-2], self.file_info)))
        self.assertEqual(self.get_num_chapters(), sum(map(lambda x: x[-1], self.file_info)))

    def test_remote_local_server(self):
        original_default = list(self.default_server_list)
        self.default_server_list.extend(filter(lambda x: x.id == LocalServer.id, LOCAL_SERVERS))
        os.unlink(self.settings.get_remote_servers_config_file())
        self.reload(True)
        local_server = self.media_reader.get_server(LocalServer.id)
        media_files = [("A", "file1"), ("A", "file2"), ("B", "file1")]
        for media_name, file_name in media_files:
            open(local_server.get_import_media_dest(media_name, file_name), "w").close()
        media_list = self.add_test_media()
        self.assertEqual(2, len(media_list))
        self.media_reader.state.save()

        remote_server_id = "remote"
        path = "path"
        with open(self.settings.get_remote_servers_config_file(), "w") as f:
            conf = {remote_server_id: {
                    "domain_list": [f"http://localhost:{self.port}"],
                    "path": path
                    }
                    }
            json.dump(conf, f)
        os.symlink(os.path.join(TEST_HOME, self.settings.data_dir), os.path.join(TEST_TEMP, path))

        self.default_server_list = original_default
        self.reload(True)
        self.assertEqual(len(self.media_reader.get_servers()), 1)

        media_list = self.add_test_media(server_id=remote_server_id)
        self.assertEqual(2, len(media_list))
        self.assertEqual(set(map(lambda x: x["name"], media_list)), set(("A", "B",)))

        self.media_reader.download_unread_chapters()
        self.verify_all_chapters_downloaded()

    def test_no_valid_domains(self):
        conf = {"remote_test_bad": {
            "domain_list": ["__bad_domain__"],
            "path": "/",
            "media_type": "ANIME",
        }}

        with open(self.settings.get_remote_servers_config_file(), "w") as f:
            json.dump(conf, f)
        self.reload(True)
        self.assertRaises(Exception, self.add_test_media)

    def test_load_credentials(self):
        conf = {
            "remote_test_load_credentials": {
                "domain_list": [f"http://localhost:{self.port}"],
                "auth": True
            },
            "remote_test_load_credentials_missing_password": {
                "domain_list": [f"http://localhost:{self.port}"],
                "auth": True,
                "username": "A",
            },
            "remote_test_load_credentials_missing_username": {
                "domain_list": [f"http://localhost:{self.port}"],
                "auth": True,
                "password": "A",
            }
        }
        with open(self.settings.get_remote_servers_config_file(), "w") as f:
            json.dump(conf, f)
        self.reload(True)
        self.assertEqual(3, len(self.media_reader.state.get_server_ids()))
        self.test_workflow()

    def test_validate_media(self):
        media_list = self.add_test_media()
        for media_data in media_list:
            self.assertTrue(media_data["name"], media_data["id"])
            self.assertFalse(media_data["name"].endswith(".test"), media_data["name"])
            self.assertFalse(media_data["name"].endswith("/"), media_data["name"])
            self.assertTrue(media_data["chapters"])

    def test_stream(self):
        self.settings.viewer = "curl -sf {media}"
        for file_info_data in self.file_info:
            if file_info_data[2] & MediaType.ANIME:
                for file_path in file_info_data[1]:
                    url = self.valid_domain + "/" + file_info_data[0] + "/" + file_path
                    with self.subTest(url=url):
                        self.assertTrue(self.media_reader.stream(url))

    def test_add_from_url(self):
        for i, file_info_data in enumerate(self.file_info):
            url = self.valid_domain + "/" + file_info_data[0] + "/" + file_info_data[1][0]
            with self.subTest(url=url):
                self.media_reader.add_from_url(url)
                self.verify_media_len(i + 1)

    def test_verify_download_resources(self):
        media_list = self.add_test_media()
        self.media_reader.download_unread_chapters()
        num_files = 0
        self.assertTrue(media_list)
        for media_data in media_list:
            self.assertTrue(media_data.get_sorted_chapters())
            for chapter_data in media_data.get_sorted_chapters():
                chapter_dir = self.settings.get_chapter_dir(media_data, chapter_data, skip_create=True)
                self.assertTrue(os.path.exists(chapter_dir))
                dir_path = os.path.join(chapter_dir, self.resources_dir_name)
                if os.path.exists(dir_path):
                    self.assertTrue(os.listdir(dir_path))
                    num_files += 1
        expected_num_files = 0
        for root, dirs, files in os.walk(TEST_TEMP):
            expected_num_files += self.resources_dir_name in dirs
        self.assertEqual(expected_num_files, num_files)


class ArgsTest(CliUnitTestClass):

    def test_help_defined(self):
        import argparse
        parser = argparse.ArgumentParser()
        sub_parsers = parser.add_subparsers(dest="type")
        setup_subparsers(self.media_reader.state, sub_parsers)
        self.assertEqual(len(set(sub_parsers._name_parser_map.values())), len(sub_parsers._choices_actions))

    def test_no_arguments(self):
        self.assertTrue(parse_args(media_reader=self.media_reader, args=[]))

    def test_no_auto_create_dirs(self):
        parse_args(media_reader=self.media_reader, args=["list"])
        self.assertFalse(os.listdir(TEST_HOME))

    @patch("builtins.input", return_value="0")
    def test_auth(self, input):
        parse_args(media_reader=self.media_reader, args=["auth"])

    @patch("builtins.input", return_value="a")
    def test_search_add_nan(self, input):
        parse_args(media_reader=self.media_reader, args=["search", "manga"])
        self.verify_no_media()

    @patch("builtins.input", return_value="1000")
    def test_search_add_out_or_range(self, input):
        parse_args(media_reader=self.media_reader, args=["search", "manga"])
        self.verify_no_media()

    def test_login(self):
        server = self.media_reader.get_server(TestServerLogin.id)
        self.assertTrue(server.needs_to_login())

        parse_args(media_reader=self.media_reader, args=["login", server.id])
        self.assertFalse(server.needs_to_login())
        server.reset()
        self.assertTrue(server.needs_to_login())
        parse_args(media_reader=self.media_reader, args=["login"])
        self.assertFalse(server.needs_to_login())

    def test_get_remaining_chapters(self):
        server = self.media_reader.get_server(TestServerLogin.id)
        self.add_test_media(server_id=server.id, limit=1)[0]

        parse_args(media_reader=self.media_reader, args=["get_remaining_chapters"])
        parse_args(media_reader=self.media_reader, args=["get_remaining_chapters", TestServerLogin.id])

    def test_test_login_fail(self):
        server = self.media_reader.get_server(TestServerLogin.id)
        server.error_login = True
        parse_args(media_reader=self.media_reader, args=["login", server.id])
        assert server.needs_to_login()

    def test_autocomplete_not_found(self):
        with patch.dict(sys.modules, {"argcomplete": None}):
            parse_args(media_reader=self.media_reader, args=["list"])

    def test_cookies(self):
        key, value = "Key", "value"
        self.media_reader.session.cookies.set(key, value)
        parse_args(media_reader=self.media_reader, args=["--clear-cookies"])
        self.assertNotEqual(self.media_reader.session.cookies.get(key), value)

    @patch("getpass.getpass", return_value="0")
    def test_set_password(self, input):
        self.media_reader.settings.password_manager_enabled = True
        self.settings.password_load_cmd = f"cat {TEST_HOME}{{server_id}} 2>/dev/null"
        self.settings.password_save_cmd = f"( echo {{username}}; cat - ) > {TEST_HOME}{{server_id}}"
        parse_args(media_reader=self.media_reader, args=["set-password", TestServerLogin.id, "username"])
        self.assertEqual(("username", "0"), self.media_reader.settings.get_credentials(TestServerLogin.id))
        parse_args(media_reader=self.media_reader, args=["get-password", TestServerLogin.id])

    def test_list_tag(self):
        self.add_test_media()
        tag_name = "test"
        parse_args(media_reader=self.media_reader, args=["untag", tag_name])
        parse_args(media_reader=self.media_reader, args=["tag", tag_name])
        self.assertTrue(all(map(lambda x: [tag_name] == x["tags"], self.media_reader.get_media())))
        parse_args(media_reader=self.media_reader, args=["list", "--tag", tag_name])
        parse_args(media_reader=self.media_reader, args=["untag", tag_name])
        parse_args(media_reader=self.media_reader, args=["list", "--tag"])

    def test_list(self):
        parse_args(media_reader=self.media_reader, args=["list"])
        self.add_test_media(no_update=True)
        parse_args(media_reader=self.media_reader, args=["list"])
        self.media_reader.update()
        parse_args(media_reader=self.media_reader, args=["list"])
        parse_args(media_reader=self.media_reader, args=["list", "--csv"])

    def test_list_tracked(self):
        self.add_test_media()
        for i in range(2):
            parse_args(media_reader=self.media_reader, args=["list", "--tracked"])
            parse_args(media_reader=self.media_reader, args=["list", "--untracked"])
            parse_args(media_reader=self.media_reader, args=["--auto", "load"])

    def test_list_from_servers(self):
        parse_args(media_reader=self.media_reader, args=["list-from-servers", TestServer.id])

    def test_list_chapters(self):
        media_data = self.add_test_media(server_id=TestServer.id, limit=1)[0]
        parse_args(media_reader=self.media_reader, args=["list-chapters", media_data["name"]])
        parse_args(media_reader=self.media_reader, args=["list-chapters", "--show-ids", media_data["name"]])

    def test_print_media_reader_state(self):
        self.add_test_media()
        chapter_id = list(self.media_reader.get_media_ids())[0]
        parse_args(media_reader=self.media_reader, args=["list-chapters", chapter_id])
        parse_args(media_reader=self.media_reader, args=["list"])
        parse_args(media_reader=self.media_reader, args=["list-servers"])

    def test_search_save(self):
        parse_args(media_reader=self.media_reader, args=["--auto", "search", "manga"])
        assert len(self.media_reader.get_media_ids())
        self.reload()
        assert len(self.media_reader.get_media_ids())

    def test_load(self):
        parse_args(media_reader=self.media_reader, args=["--auto", "search", "--server", TestServer.id, "InProgress"])
        assert len(self.media_reader.get_media_ids()) == 1
        media_data = next(iter(self.media_reader.get_media()))
        parse_args(media_reader=self.media_reader, args=["--auto", "load", "--local-only", "test_user"])
        assert self.media_reader.get_tracker_info(media_data)
        self.assertEqual(media_data["progress"], media_data.get_last_read_chapter_number())

    def test_load_resolve_media_type(self):
        media_list = self.add_test_media(server_id=TestUnofficialServer.id)
        self.assertFalse(any(media_data["media_type_name"] for media_data in media_list))
        parse_args(media_reader=self.media_reader, args=["--auto", "load", "--local-only", "test_user"])
        for media_data in media_list:
            if self.media_reader.get_tracker_info(media_data):
                self.assertTrue(media_data["media_type_name"])
                self.assertTrue(MediaType(media_data["media_type"]).name)

    def test_load_filter_by_type(self):
        parse_args(media_reader=self.media_reader, args=["--auto", "load", f"--media-type={MediaType.ANIME.name}", "test_user"])
        assert all([x["media_type"] == MediaType.ANIME for x in self.media_reader.get_media()])

    def test_load_remove(self):
        parse_args(media_reader=self.media_reader, args=["--auto", "load", "test_user"])
        self.media_reader.get_tracker().set_custom_anime_list([], MediaType.ANIME)
        parse_args(media_reader=self.media_reader, args=["--auto", "load", "--remove", f"--media-type={MediaType.ANIME.name}", "test_user"])
        self.assertFalse(list(self.media_reader.get_media(media_type=MediaType.ANIME)))

    def test_load_remove_untracked(self):
        self.add_test_media(server_id=TestServer.id)
        media_ids = set(self.media_reader.get_media_ids())
        parse_args(media_reader=self.media_reader, args=["--auto", "load", "--server", TestServer.id, "--remove", "test_user"])
        self.assertEqual(media_ids, self.media_reader.get_media_ids())

    def test_load_add_progress_only(self):
        parse_args(media_reader=self.media_reader, args=["--auto", "load", "--no-add", "test_user"])
        assert not self.media_reader.get_media_ids()

    def test_load_add_new_media(self):
        parse_args(media_reader=self.media_reader, args=["--auto", "load", "test_user"])
        assert len(self.media_reader.get_media_ids()) > 1
        for media_data in self.media_reader.get_media():
            assert self.media_reader.get_tracker_info(media_data)
            if media_data["progress"]:
                self.assertEqual(media_data["progress"], media_data.get_last_read_chapter_number())

    def test_load_sort_by_lang(self):
        self.assertEqual(float("inf"), self.settings.get_prefered_lang_key(None, "bad"))
        for server in (self.test_server, self.test_anime_server):
            server.test_lang = True
            for lang in ("EN", "JP"):
                self.media_reader.media.clear()
                self.settings.search_score = [["lang", [lang, lang.lower()], -1]]
                self.assertNotEqual(float("inf"), self.settings.get_prefered_lang_key(None, lang))
                with self.subTest(lang=lang, server=server.id):
                    parse_args(media_reader=self.media_reader, args=["--auto", "load", "--media-type", server.media_type.name, "--server", server.id, "test_user"])
                    self.assertEqual(1, len(self.media_reader.get_media_ids()))
                    media_data = list(self.media_reader.get_media())[0]
                    self.assertEqual(media_data["lang"].upper(), lang)

    def test_untrack(self):
        parse_args(media_reader=self.media_reader, args=["--auto", "load"])
        assert all([self.media_reader.get_tracker_info(media_data) for media_data in self.media_reader.get_media()])
        parse_args(media_reader=self.media_reader, args=["untrack"])
        assert not any([self.media_reader.get_tracker_info(media_data) for media_data in self.media_reader.get_media()])

    def test_copy_tracker(self):
        media_list = self.add_test_media()
        self.media_reader.get_tracker().set_custom_anime_list([media_list[0]["name"]], media_list[0]["media_type"])
        parse_args(media_reader=self.media_reader, args=["--auto", "load", "test_user"])
        assert self.media_reader.get_tracker_info(media_list[0])
        assert not self.media_reader.get_tracker_info(media_list[1])
        parse_args(media_reader=self.media_reader, args=["copy-tracker", media_list[0]["name"], media_list[1]["name"]])
        self.assertEqual(self.media_reader.get_tracker_info(media_list[0]), self.media_reader.get_tracker_info(media_list[1]))

    def test_stats(self):
        self.add_test_media()
        parse_args(media_reader=self.media_reader, args=["stats", "test_user"])
        parse_args(media_reader=self.media_reader, args=["stats", "--media-type", MediaType.ANIME.name, "test_user"])
        parse_args(media_reader=self.media_reader, args=["stats", "-s", "NAME", "test_user"])
        parse_args(media_reader=self.media_reader, args=["stats", "-g", "NAME", "test_user"])
        parse_args(media_reader=self.media_reader, args=["stats", "-d", "NAME", "test_user"])

    def test_stats_default_user(self):
        self.add_test_media()
        parse_args(media_reader=self.media_reader, args=["stats"])

    def test_stats_refresh(self):
        self.add_test_media()
        parse_args(media_reader=self.media_reader, args=["stats-update"])
        parse_args(media_reader=self.media_reader, args=["stats"])
        parse_args(media_reader=self.media_reader, args=["stats-update"])

    def test_mark_read(self):
        media_list = self.add_test_media()
        media_data = media_list[0]
        name = media_data.global_id
        parse_args(media_reader=self.media_reader, args=["mark-read", name])
        self.verify_all_chapters_read(name=media_data)

        parse_args(media_reader=self.media_reader, args=["mark-read", "--force", name, "-1"])
        assert not all(map(lambda x: x["read"], media_data["chapters"].values()))
        parse_args(media_reader=self.media_reader, args=["mark-unread", name])
        assert not any(map(lambda x: x["read"], media_data["chapters"].values()))

    def test_mark_read_progress(self):
        parse_args(media_reader=self.media_reader, args=["--auto", "load", "--server", TestServer.id])
        media_data = next(self.media_reader.get_media())
        parse_args(media_reader=self.media_reader, args=["mark-read", self.test_server.id])
        parse_args(media_reader=self.media_reader, args=["sync"])
        self.assertEqual(media_data["progress"], media_data.get_last_read_chapter_number())
        self.verify_all_chapters_read()

        self.test_server.hide = True
        parse_args(media_reader=self.media_reader, args=["update"])
        self.assertNotEqual(media_data["progress"], media_data.get_last_read_chapter_number())
        self.test_server.hide = False
        parse_args(media_reader=self.media_reader, args=["update"])

        parse_args(media_reader=self.media_reader, args=["mark-read", "--progress"])
        self.verify_all_chapters_read()
        self.assertEqual(media_data["progress"], media_data.get_last_read_chapter_number())

    def test_sync_progress(self):
        parse_args(media_reader=self.media_reader, args=["--auto", "load"])
        parse_args(media_reader=self.media_reader, args=["mark-read"])
        parse_args(media_reader=self.media_reader, args=["sync"])
        for i in range(2):
            for media_data in self.media_reader.get_media():
                self.assertEqual(media_data.get_last_chapter()["number"], media_data.get_last_read_chapter_number())
                self.assertEqual(media_data["progress"], media_data.get_last_read_chapter_number())
            self.reload()

    def test_download(self):
        self.add_test_media(server_id=TestServer.id, limit=1)
        parse_args(media_reader=self.media_reader, args=["download-unread"])
        self.verify_all_chapters_downloaded()
        self.settings.chapter_dir_name_format = "{chapter_title} {chapter_number:07.2f}"
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
        self.add_test_media(TestServer.id)
        for id, media_data in self.media_reader.media.items():
            server = self.media_reader.get_server(media_data["server_id"])
            chapter = list(filter(lambda x: not x["special"], media_data.get_sorted_chapters()))[0]
            parse_args(media_reader=self.media_reader, args=["download-unread", "--limit", "1", id])
            self.assertEqual(0, server.download_chapter(media_data, chapter))

    def test_update(self):
        media_list = self.add_test_media(no_update=True)
        self.assertEqual(len(media_list[0]["chapters"]), 0)
        parse_args(media_reader=self.media_reader, args=["update"])
        self.assertTrue(media_list[0]["chapters"])

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
        media_data = self.add_test_media(server_id=TestServer.id, limit=1)[0]
        chapters = media_data["chapters"]
        list_of_numbers = sorted([chapter_data["number"] for chapter_data in chapters.values()])
        offset_list = list(map(lambda x: x - 1, list_of_numbers))
        parse_args(media_reader=self.media_reader, args=["offset", media_data.global_id, "1"])
        self.assertEqual(offset_list, sorted([chapter_data["number"] for chapter_data in chapters.values()]))
        parse_args(media_reader=self.media_reader, args=["update"])
        self.assertEqual(offset_list, sorted([chapter_data["number"] for chapter_data in chapters.values()]))

    def test_offset_none(self):
        def update_media_data(media_data):
            self.test_server.update_chapter_data(media_data, id=1, title="1", number=0)
            self.test_server.update_chapter_data(media_data, id=2, title="2", number=20)
            self.test_server.update_chapter_data(media_data, id=3, title="3", number=30)
        self.test_server.update_media_data = update_media_data
        media_data = self.add_test_media(server_id=TestServer.id, limit=1)[0]
        parse_args(media_reader=self.media_reader, args=["offset", media_data.global_id])
        self.assertEqual(19, media_data["offset"])
        self.assertEqual(1, media_data.get_first_chapter_number_greater_than_zero())

    def test_search(self):
        parse_args(media_reader=self.media_reader, args=["--auto", "search", "manga"])
        media_data = self.media_reader.get_single_media()
        self.assertTrue(media_data)
        # shouldn't throw error nor add duplicate media.
        # An Exception can still be raised if the name wasn't an exact match
        parse_args(media_reader=self.media_reader, args=["--auto", "search", media_data["name"]])
        self.assertEqual(1, len(self.media_reader.get_media_ids()))

    def test_search_fail(self):
        parse_args(media_reader=self.media_reader, args=["--auto", "search", "__UnknownMedia__"])

    def test_migrate_offset(self):
        media_data = self.add_test_media(TestServer.id)[0]
        parse_args(media_reader=self.media_reader, args=["offset", media_data.global_id, "1"])
        parse_args(media_reader=self.media_reader, args=["--auto", "migrate", "--self", media_data["name"]])
        for i in range(2):
            media_data = self.media_reader.get_single_media(name=media_data.global_id)
            self.assertEqual(media_data["offset"], 1)
            self.media_reader.state.all_media["version"] = 0
            self.media_reader.upgrade_state()

    def test_migrate(self):

        media_list = self.add_test_media(TestServer.id)
        parse_args(media_reader=self.media_reader, args=["--auto", "load", "--local-only"])
        self.media_reader.mark_read()
        parse_args(media_reader=self.media_reader, args=["--auto", "migrate", "--exact", self.test_server.id])
        self.assertEqual(len(self.media_reader.get_media_ids()), len(media_list))

        for media_data in media_list:
            media_data2 = self.media_reader.get_single_media(name=media_data["name"])
            if not media_data.get("unique", False):
                self.assertNotEqual(media_data.global_id, media_data2.global_id)
            self.assertEqual(media_data.get_last_read_chapter_number(), media_data2.get_last_read_chapter_number())
            self.assertEqual(media_data["progress"], media_data2["progress"])
            self.assertEqual(self.media_reader.get_tracker_info(media_data), self.media_reader.get_tracker_info(media_data2))

    def test_migrate_self(self):
        media_list = self.add_test_media(TestServer.id)
        parse_args(media_reader=self.media_reader, args=["--auto", "load", "--local-only"])
        self.media_reader.mark_read()
        parse_args(media_reader=self.media_reader, args=["--auto", "migrate", "--self", "--force-same-id", self.test_server.id])
        self.assertEqual(len(self.media_reader.get_media_ids()), len(media_list))

        for media_data in media_list:
            self.assertEqual(media_data, self.media_reader.get_single_media(name=media_data.global_id))

    def test_remove(self):
        parse_args(media_reader=self.media_reader, args=["--auto", "search", "manga"])
        media_id = list(self.media_reader.get_media_ids())[0]
        parse_args(media_reader=self.media_reader, args=["remove", media_id])
        self.verify_no_media()

    def test_clean_removed(self):
        self.add_test_media(TestServer.id)
        self.media_reader.download_unread_chapters()
        self.media_reader.media.clear()

        parse_args(media_reader=self.media_reader, args=["clean"])
        for dir in os.listdir(self.settings.media_dir):
            self.assertEqual(0, len(os.listdir(os.path.join(self.settings.media_dir, dir))))

    def test_clean_noop(self):
        self.add_test_media(TestServer.id, limit=1)
        self.media_reader.download_unread_chapters()
        parse_args(media_reader=self.media_reader, args=["clean"])
        self.verify_all_chapters_downloaded()

    def test_clean_read(self):
        self.add_test_media(TestServer.id)
        self.media_reader.download_unread_chapters()
        parse_args(media_reader=self.media_reader, args=["clean"])
        self.verify_all_chapters_downloaded()
        self.media_reader.mark_read()
        parse_args(media_reader=self.media_reader, args=["clean"])
        self.verify_all_chapters_downloaded()

        parse_args(media_reader=self.media_reader, args=["clean", "--remove-read"])
        self.verify_no_chapters_downloaded()

    def test_clean_stream(self):
        media_data = self.add_test_media(media_type=MediaType.ANIME, limit=1)[0]
        parse_args(media_reader=self.media_reader, args=["play"])
        self.verify_no_chapters_downloaded()
        parse_args(media_reader=self.media_reader, args=["clean"])

        for chapter_data in media_data.get_sorted_chapters():
            self.assertFalse(os.path.exists(self.settings.get_chapter_dir(media_data, chapter_data, skip_create=True)))

    def test_clean_read_already_removed(self):
        media_data = self.add_test_media(TestServer.id, limit=1)[0]
        self.media_reader.download_unread_chapters()
        self.media_reader.mark_read()
        self.media_reader.state.save()
        media_data["chapters"].clear()
        self.media_reader.state.save()
        parse_args(media_reader=self.media_reader, args=["clean"])
        self.assertEqual(1, len(os.listdir(self.settings.get_media_dir(media_data))))

    def test_clean_servers(self):
        self.add_test_media(TestServer.id)
        parse_args(media_reader=self.media_reader, args=["download-unread", "--limit=1"])
        self.media_reader._servers.clear()
        parse_args(media_reader=self.media_reader, args=["clean", "--remove-disabled-servers"])
        self.assertFalse(os.listdir(self.settings.media_dir))

    def test_clean_unused(self):
        self.add_test_media(TestServer.id)
        parse_args(media_reader=self.media_reader, args=["clean", "--remove-not-on-disk"])
        self.assertEqual(0, len(os.listdir(self.settings.get_server_dir(TestServer.id))))

    def test_clean_web_cache(self):
        parse_args(media_reader=self.media_reader, args=["clean", "--url-cache"])
        os.makedirs(self.settings.get_web_cache_dir())
        with open(os.path.join(self.settings.get_web_cache_dir(), "file"), "w") as f:
            f.write("dummy_data")
        parse_args(media_reader=self.media_reader, args=["clean", "--url-cache"])
        self.assertFalse(os.path.exists(self.settings.get_web_cache_dir()))

    def test_consume(self):
        self.add_test_media(limit_per_server=1)
        parse_args(media_reader=self.media_reader, args=["--auto", "consume"])
        self.verify_all_chapters_read()

    def test_consume_normal(self):
        self.add_test_media(server_id=TestServer.id, limit=1)
        parse_args(media_reader=self.media_reader, args=["consume"])
        self.verify_all_chapters_read()

    def test_view(self):
        self.add_test_media(media_type=MediaType.MANGA | MediaType.NOVEL, limit_per_server=2)
        parse_args(media_reader=self.media_reader, args=["--auto", "view"])
        self.verify_all_chapters_read()

    def test_play(self):
        self.add_test_media(media_type=MediaType.ANIME, limit_per_server=2)
        parse_args(media_reader=self.media_reader, args=["--auto", "play"])
        self.verify_all_chapters_read()

    def test_play_fail(self):
        self.add_test_media(TestAnimeServer.id)

        self.settings.viewer = "exit 1"
        parse_args(media_reader=self.media_reader, args=["play"])
        assert not self.get_num_chapters_read(MediaType.ANIME)

    def test_play_specific(self):
        media_data = self.add_test_media(TestAnimeServer.id)[0]
        parse_args(media_reader=self.media_reader, args=["play", media_data["name"], "1", "3"])
        for chapter in media_data.get_sorted_chapters():
            self.assertEqual(chapter["read"], chapter["number"] in [1, 3])

    def test_play_relative(self):
        media_data = self.add_test_media(TestAnimeServer.id, limit=1)[0]
        chapters = list(media_data.get_sorted_chapters())
        chapters[1]["read"] = True
        parse_args(media_reader=self.media_reader, args=["play", media_data["name"], "-1"])
        assert chapters[0]["read"]

    def test_play_last_read(self):
        media_data = self.add_test_media(TestAnimeServer.id, limit=1)[0]
        chapters = list(media_data.get_sorted_chapters())
        chapters[1]["read"] = True
        parse_args(media_reader=self.media_reader, args=["play", media_data["name"], "0"])
        self.assertEqual(1, self.get_num_chapters_read(MediaType.ANIME))

    def test_play_extra_args(self):
        self.add_test_media(TestAnimeServer.id, limit=1)[0]
        self.settings.viewer = '[ -z "$AMT_USER_ARGS" ]'
        self.assertEqual(0, parse_args(media_reader=self.media_reader, args=["play"]))
        self.settings.viewer = '[ "$AMT_USER_ARGS" = --extra ]'
        os.environ["AMT_USER_ARGS"] = "--extra"
        self.assertEqual(0, parse_args(media_reader=self.media_reader, args=["play"]))

    def test_get_stream_url(self):
        self.add_test_media(TestAnimeServer.id)
        parse_args(media_reader=self.media_reader, args=["get-stream-url"])
        assert not self.get_num_chapters_read(MediaType.ANIME)

    def test_stream(self):
        parse_args(media_reader=self.media_reader, args=["stream", TestAnimeServer.get_streamable_url()])
        self.verify_no_media()

    def stream_error(self):
        assert parse_args(media_reader=self.media_reader, args=["stream", "bad_url"])

    def test_stream_temp(self):
        self.add_test_media(TestAnimeServer.id, limit=1)
        parse_args(media_reader=self.media_reader, args=["--tmp-dir", "stream", TestServer.get_streamable_url()])
        assert not os.path.exists(self.settings.get_metadata_file())
        self.reload()
        self.verify_no_media()

    def test_stream_quality(self):
        parse_args(media_reader=self.media_reader, args=["stream", "-q", "-1", TestAnimeServer.get_streamable_url()])

    def test_stream_download(self):
        parse_args(media_reader=self.media_reader, args=["stream", "--download", TestAnimeServer.get_streamable_url()])
        self.verify_no_media()
        server = self.media_reader.get_server(TestAnimeServer.id)
        media_data = server.get_media_data_from_url(TestAnimeServer.get_streamable_url())
        server.update_media_data(media_data)
        chapter_data = media_data["chapters"][server.get_chapter_id_for_url(TestAnimeServer.get_streamable_url())]
        self.verify_download(media_data, chapter_data)

    def test_download_stream(self):
        parse_args(media_reader=self.media_reader, args=["stream", "--download", TestAnimeServer.get_streamable_url()])
        parse_args(media_reader=self.media_reader, args=["stream", TestAnimeServer.get_streamable_url()])

    def test_add_from_url_stream_cont_record(self):
        parse_args(media_reader=self.media_reader, args=["stream", "--cont", TestAnimeServer.get_streamable_url()])
        self.verify_no_media()
        parse_args(media_reader=self.media_reader, args=["stream", "--record", TestAnimeServer.get_streamable_url()])
        self.assertTrue(self.media_reader.get_single_media())
        self.assertEqual(1, self.get_num_chapters_read())
        parse_args(media_reader=self.media_reader, args=["stream", "--cont", TestAnimeServer.get_streamable_url()])
        self.assertEqual(1, self.get_num_chapters_read())
        parse_args(media_reader=self.media_reader, args=["stream", "--cont", "--record", TestAnimeServer.get_streamable_url()])
        self.verify_all_chapters_read(media_type=MediaType.ANIME)
        self.media_reader.get_single_media()["chapters"].clear()
        parse_args(media_reader=self.media_reader, args=["stream", "--cont", "--record", TestAnimeServer.get_streamable_url()])
        self.verify_all_chapters_read(media_type=MediaType.ANIME)

    def test_add_from_url_bad(self):
        assert parse_args(media_reader=self.media_reader, args=["add-from-url", "bad-url"])
        self.verify_no_media()

    def import_test_setup(self, parent_dir="", file_name="Anime1 - E10.jpg"):
        media_name = "[author] test dir"
        path = os.path.join(TEST_HOME, parent_dir, media_name)
        os.makedirs(path, exist_ok=True)
        path_file = os.path.join(path, file_name)
        open(path_file, "w").close()
        return media_name, file_name, path, path_file

    def verify_import_test(self, media_name, chapter_title):
        media_data = self.media_reader.get_single_media(name=media_name)
        self.assertTrue(any(map(lambda x: x["title"] == chapter_title, media_data.get_sorted_chapters())))

    def test_import(self):
        media_name, chapter_title, path, path_file = self.import_test_setup()
        parse_args(media_reader=self.media_reader, args=["import", "--name", media_name, path_file])
        self.verify_import_test(media_name, chapter_title)

    def test_import_bad(self):
        media_name, chapter_title, path, path_file = self.import_test_setup()
        parse_args(media_reader=self.media_reader, args=["import", path_file])
        self.verify_no_media()

    def test_import_update(self):
        media_name, chapter_title, path, path_file = self.import_test_setup(file_name="A 01.txt")
        parse_args(media_reader=self.media_reader, args=["import", "--name", media_name, path_file])
        media_name, chapter_title, path, path_file = self.import_test_setup(file_name="A 02.txt")
        parse_args(media_reader=self.media_reader, args=["import", "--name", media_name, path_file])
        self.verify_import_test(media_name, chapter_title)

    def test_import_directory(self):
        media_name, chapter_title, path, path_file = self.import_test_setup()
        self.assertTrue(os.path.exists(path_file))
        parse_args(media_reader=self.media_reader, args=["import", "--link", path])
        self.assertTrue(os.path.exists(path_file))
        self.verify_import_test(media_name, chapter_title)

    def test_import_directory_self(self):
        media_name, chapter_title, path, _ = self.import_test_setup()
        os.chdir(path)
        parse_args(media_reader=self.media_reader, args=["import", "."])
        self.verify_import_test(media_name, chapter_title)

    def test_import_nested_directory(self):
        parent_dir = "dir1"
        media_name, chapter_title, path, _ = self.import_test_setup(parent_dir=parent_dir)
        parse_args(media_reader=self.media_reader, args=["import", "--name", media_name, parent_dir])
        self.verify_import_test(media_name, chapter_title)

    def _test_upgrade_helper(self, minor):
        self.add_test_media(TestAnimeServer.id)
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
        parse_args(media_reader=self.media_reader, args=["upgrade"] if not minor else ["--auto"])
        self.assertEqual(list(self.media_reader.get_media_ids()), ids)
        self.assertEqual(removed_key in self.media_reader.media[ids[0]], minor)
        self.assertTrue(new_key in self.media_reader.media[ids[0]])
        if not minor:
            self.assertTrue(all(["special" in x for x in self.media_reader.media[ids[1]]["chapters"].values()]))
            self.assertTrue(all(["old_chapter_field" not in x for x in self.media_reader.media[ids[2]]["chapters"].values()]))
        self.assertTrue(all([media_data.get_last_read_chapter()["number"] == media_data.get_last_chapter()["number"] for media_data in self.media_reader.get_media()]))

    def test_upgrade_minor(self):
        self._test_upgrade_helper(True)

    def test_upgrade_major(self):
        self._test_upgrade_helper(False)

    def test_default_version(self):
        self.assertFalse(self.media_reader.state.is_out_of_date_minor())
        self.assertFalse(self.media_reader.state.is_out_of_date())

    def test_upgrade_server_version(self):
        media_data = self.add_test_media(TestServer.id, limit=1)[0]
        del media_data["version"]
        self.media_reader.mark_read()
        self.test_server.version = 1

        ids = set(media_data["chapters"].keys())
        for chapter_id in ids:
            new_chapter_id = f"{chapter_id}_new"
            media_data["chapters"][new_chapter_id] = media_data["chapters"][chapter_id]
            media_data["chapters"][new_chapter_id]["id"] = new_chapter_id
            del media_data["chapters"][chapter_id]

        self.media_reader.upgrade_state_if_server_version_changed()
        self.assertEquals(ids, set(media_data["chapters"].keys()))
        self.verify_all_chapters_read(media_data)


class RealServerTest(GenericServerTest, RealBaseUnitTestClass):

    def test_cookie_saving(self):
        sessions = []
        self.settings.no_save_session = False
        for server in self.media_reader.get_servers():
            if server.session not in sessions:
                with self.subTest(server=server.id):
                    sessions.append(server.session)
                    self.assertFalse(server.session.cookies)
                    r = server.session_get("https://github.com")
                    self.assertTrue(r.cookies)
                    self.assertEqual(server.session.cookies, self.media_reader.session.cookies)
                    self.assertTrue(server.session.cookies is self.media_reader.session.cookies)
                    self.assertTrue(self.media_reader.state.save_session_cookies())
                    server.session.cookies.clear()
                    self.assertTrue(self.media_reader.state.save_session_cookies())
        self.assertEqual(min(2, len(self.media_reader.state.get_server_ids())), len(sessions))

    def test_search(self):
        for media_type in list(MediaType) + [None]:
            if media_type and not list(filter(lambda x: media_type & x.media_type, self.media_reader.get_servers())):
                self.skipTest("Server not enabled")
            with self.subTest(media_type=media_type):
                self.assertTrue(self.media_reader.search_add("one", media_type=media_type, limit=1, no_add=True))


class ServerStreamTest(RealBaseUnitTestClass):
    streamable_urls = [
        ("https://crunchyroll.com/manga/talentless-nana/read/1", "519", None, "17221"),
        ("https://crunchyroll.com/watch/GR3VWXP96/Im-Luffy-The-Man-Whos-Gonna-Be-King-of-the-Pirates", "257631", "21685", "GR3VWXP96"),
        ("https://dragonball-multiverse.com/en/chapters.html?comic=page&chapter=80", "1", None, "80"),
        ("https://dragonball-multiverse.com/en/page-1854.html#h_read", "1", None, "80"),
        ("https://freewebnovel.com/itai-no-wa-iya-nanode-bgyo-ryoku-ni-kyokufuri-shitai-to-omoimasu/chapter-1.html", "itai-no-wa-iya-nanode-bgyo-ryoku-ni-kyokufuri-shitai-to-omoimasu", None, "chapter-1"),
        ("https://funimation.com/v/one-piece/im-luffy-the-man-whos-gonna-be-king-of-the-pirates", "20224", "20227", "22338"),
        ("https://hidive.com/stream/o-maidens-in-your-savage-season/s01e001", "o-maidens-in-your-savage-season", None, "s01e001"),
        ("https://j-novel.club/read/i-refuse-to-be-your-enemy-volume-1-part-1", "i-refuse-to-be-your-enemy", None, "i-refuse-to-be-your-enemy-volume-1-part-1"),
        ("https://j-novel.club/read/seirei-gensouki-spirit-chronicles-manga-volume-1-chapter-1", "seirei-gensouki-spirit-chronicles-manga", None, "seirei-gensouki-spirit-chronicles-manga-volume-1-chapter-1"),
        ("https://mangadex.org/chapter/ea697e18-470c-4e80-baf0-a3972720178f/1", "8a3d319d-2d10-4364-928c-0f30fd367c24", None, "ea697e18-470c-4e80-baf0-a3972720178f"),
        ("https://mangaplus.shueisha.co.jp/viewer/1000486", "100020", None, "1000486"),
        ("https://mangasee123.com/read-online/Bobobo-Bo-Bo-Bobo-chapter-214-page-1.html", "Bobobo-Bo-Bo-Bobo", None, "102140"),
        ("https://mangasee123.com/read-online/Onepunch-Man-chapter-147-index-2-page-1.html", "Onepunch-Man", None, "201470"),
        ("https://viz.com/shonenjump/one-piece-chapter-1/chapter/5090?action=read", "one-piece", None, "5090"),
        ("https://webtoons.com/en/drama/lookism/ep-283-hostel-epilogue/viewer?title_no=1049&episode_no=283", "1049", None, "283"),
    ]

    premium_streamable_urls = [
        ("https://www.funimation.com/v/bofuri-i-dont-want-to-get-hurt-so-ill-max-out-my-defense/defense-and-first-battle/?lang=japanese", "1019573", "1019574", "1019900"),
    ]
    addable_urls = [
        ("https://crunchyroll.com/comics/manga/hoshi-no-samidare-the-lucifer-and-biscuit-hammer/volumes", 255),
        ("https://crunchyroll.com/lycoris-recoil", "282895"),
        ("https://crunchyroll.com/series/GRMG8ZQZR/", "257631"),
        ("https://hidive.com/tv/o-maidens-in-your-savage-season", "o-maidens-in-your-savage-season"),
        ("https://j-novel.club/series/monster-tamer", "monster-tamer"),
        ("https://mangaplus.shueisha.co.jp/titles/100020", 100020),
        ("https://mangasee123.com/manga/Mairimashita-Iruma-kun", "Mairimashita-Iruma-kun"),
        ("https://mangasee123.com/manga/Gunslinger-Girl", "Gunslinger-Girl"),
        ("https://nyaa.si/view/135283", "135283"),
        ("https://nyaa.si/view/269191", "269191"),
        ("https://viz.com/shonenjump/chapters/my-hero-academia-vigilantes", "my-hero-academia-vigilantes"),
        ("https://webtoons.com/en/drama/lookism/list?title_no=1049", 1049),
    ]

    def test_a_verify_valid_stream_urls(self):
        for streamable, url_list in [(True, self.streamable_urls), (False, self.addable_urls)]:
            for url_data in url_list:
                sample_url = url_data[0]
                for url in {sample_url, sample_url[:-1] if sample_url[-1] == "/" else sample_url, sample_url.replace("https:", "http:"), sample_url.replace("://", "://www.")}:
                    with self.subTest(url=url):
                        self.assert_server_enabled_or_skip_test(self.media_reader.get_server_for_url(url, streamable)[1])

    def validate_url_data(self, media_data, url_data):
        url, media_id, = url_data[0:2]
        _, server = self.media_reader.get_server_for_url(url)
        self.assert_server_enabled_or_skip_test(server)
        assert media_data
        if not media_data["chapters"]:
            server.update_media_data(media_data)
        self.assertEqual(str(media_id), str(media_data["id"]))
        if len(url_data) > 2:
            season_id, chapter_id = url_data[2:4]
            if season_id:
                self.assertEqual(str(season_id), str(media_data["season_id"]))
            if chapter_id:
                self.assertEqual(str(chapter_id), str(server.get_chapter_id_for_url(url)))
                self.assertTrue(media_data["chapters"])
                self.assertIn(str(chapter_id), list(map(str, media_data["chapters"].keys())))

    def test_get_media_data_from_url(self):
        def func(url_data):
            url = url_data[0]
            with self.subTest(url=url):
                media_data = self.media_reader.add_from_url(url, skip_add=True)
                self.validate_url_data(media_data, url_data)
        self.for_each(func, self.streamable_urls + self.addable_urls)

    def test_add_media_from_url(self):
        def func(url_data):
            url = url_data[0]
            with self.subTest(url=url):
                media_data = self.media_reader.add_from_url(url, skip_add=True)
                self.validate_url_data(media_data, url_data)
        self.for_each(func, self.addable_urls)

    def test_media_stream(self):
        def func(url_data):
            url = url_data[0]
            with self.subTest(url=url):
                _, server = self.media_reader.get_server_for_url(url)
                self.assert_server_enabled_or_skip_test(server)
                if server.media_type == MediaType.ANIME and server.has_free_chapters:
                    self.assertTrue(self.media_reader.stream(url))
        self.for_each(func, self.streamable_urls)


class TrackerTest(RealBaseUnitTestClass):

    def test_validate_tracker_info(self):
        keys_for_lists_of_strings = ["external_links", "genres", "streaming_links", "studio", "tags"]
        keys_for_strings = ["name", "season"]

        for tracker_id in self.media_reader.get_tracker_ids():
            with self.subTest(tracker_id=tracker_id):
                tracker = self.media_reader.get_tracker_by_id(tracker_id)
                self.assertTrue(tracker.get_auth_url())
                data = list(tracker.get_full_list_data(id=1))
                assert data
                for tracker_data in data:
                    assert isinstance(tracker_data, dict)
                    for key, value in tracker_data.items():
                        if key == "media_type":
                            assert isinstance(value, MediaType)
                        elif key in keys_for_lists_of_strings:
                            assert isinstance(value, list)
                            for item in value:
                                assert isinstance(item, str), f"{key}: {value}, should be a list of strings"
                        elif key in keys_for_strings:
                            assert isinstance(value, str), f"{key}: {value}, should be a string"
                        elif key != "id" and value:
                            float(value)

    def test_load_from_tracker(self):
        for tracker_id in self.media_reader.get_tracker_ids():
            with self.subTest(tracker_id=tracker_id):
                self.media_reader.set_tracker(tracker_id)
                parse_args(media_reader=self.media_reader, args=["--auto", "load", "--user-id", "1"])


class ServerSpecificTest(RealBaseUnitTestClass):
    def test_magnasee_alternative_chapter_url(self):
        url = "https://mangasee123.com/read-online/Onepunch-Man-chapter-148-index-2-page-1.html"
        self.media_reader.stream(url, download=True)

    def test_jnovel_club_parts_autodelete(self):
        from ..servers.jnovelclub import JNovelClubParts
        server = self.media_reader.get_server(JNovelClubParts.id)
        self.assert_server_enabled_or_skip_test(server)
        server.time_to_live_sec = 0
        for media_data in server.list_media():
            self.media_reader.add_media(media_data)
            if media_data["chapters"] and media_data.get_last_chapter()["volume_number"] > 1:
                break
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


def load_tests(loader, tests, pattern):
    clazzes = inspect.getmembers(sys.modules[__name__], inspect.isclass)
    test_cases = [c for _, c in clazzes if issubclass(c, BaseUnitTestClass)]
    test_cases.sort(key=lambda f: findsource(f)[1])
    suite = unittest.TestSuite()
    for test_class in test_cases:
        tests = loader.loadTestsFromTestCase(test_class)
        suite.addTests(tests)
    return suite
