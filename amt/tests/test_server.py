import os
import re

from datetime import datetime
from requests.exceptions import HTTPError
import requests

from ..server import Server
from ..util.media_type import MediaType
from ..util.progress_type import ProgressType

TEST_BASE = "/tmp/amt/"


class FakeSession(requests.Session):
    def __init__(self, session):
        super().__init__()
        self.response = requests.Response()
        self.response.status_code = 200
        self.cookies = session.cookies

    def get(self, *args, **kwargs):
        return self.response

    def post(self, *args, **kwargs):
        return self.response

    def close(self, *args, **kwargs):
        return self.response


class TestServer(Server):
    id = "test_server_manga"
    error_to_inject = None
    time_to_error = 0
    error_count = 0
    hide = False
    inaccessible = False
    error_delay = 0
    test_lang = False
    offset_chapter_num = 0
    use_real_cloud_scraper = False

    def __init__(self, session, *args, no_fake_session=False, **kwargs):
        super().__init__(FakeSession(session) if not no_fake_session else session, *args, **kwargs)
        self.stream_url_regex = re.compile(f"{self.id}/([0-9]*)/([0-9]*)")
        self.add_series_url_regex = re.compile(f"{self.id}/([0-9]*)")
        self.timestamp = datetime.now().timestamp()
        self.domain = f"{self.id}.com"

    def get_cloudscraper_session(self, *args, **kwargs):
        return self.session if not self.maybe_need_cloud_scraper and isinstance(self.session, FakeSession) else super().get_cloudscraper_session(*args, **kwargs)

    def backoff(self, *args, **kwargs):
        pass

    @classmethod
    def get_streamable_url(clzz, media_id=4, chapter_id=1):
        return clzz.get_addable_url(media_id=media_id) + f"/{chapter_id}"

    @classmethod
    def get_addable_url(clzz, media_id=5):
        return f"https://{clzz.id}/{media_id}"

    def get_chapter_id_for_url(self, url):
        assert self.can_stream_url(url)
        return self.stream_url_regex.search(url).group(2)

    def get_media_data_from_url(self, url):
        media_id = self._get_media_id_from_url(url)
        for media_data in self.get_media_list():
            if str(media_data["id"]) == media_id:
                return media_data
        return None

    def maybe_inject_error(self):
        if self.error_to_inject:
            if self.error_delay > 0:
                self.error_delay -= 1
                return
            self.error_count += 1
            try:
                raise self.error_to_inject
            finally:
                self.time_to_error -= 1
                if self.time_to_error == 0:
                    self.inject_error(None, 0)

    def inject_error(self, error=ValueError("Dummy error"), count=1, delay=0):
        self.error_to_inject = error
        self.time_to_error = count
        self.error_delay = delay

    def was_error_thrown(self):
        return self.error_count

    def get_media_list(self, **kwargs):
        self.maybe_inject_error()
        if self.test_lang:
            return [self.create_media_data(id=1, name=f"{self.media_type.name}1 (Dub)", lang="en"), self.create_media_data(id=2, name=f"{self.media_type.name}1", lang="jp")]
        return [self.create_media_data(id=1, name=f"{self.media_type.name}1", lang=None), self.create_media_data(id=2, name=f"{self.media_type.name}InProgress", lang=None), self.create_media_data(id=3, name="Untracked (Dub)", lang=None), self.create_media_data(id=4, name="!@#$%^&* 's\",.?)(]/[:;_-= (French Dub)"), self.create_media_data(id=5, name=f"{self.id} Unique Manga", alt_id="alt", unique=True)]

    def update_media_data(self, media_data):
        self.maybe_inject_error()
        if self.hide:
            return
        media_id = media_data["id"]
        if self.media_type != MediaType.ANIME:
            deltas = [0, 30, 60 * 2, 3600 * 2, 3600 * 24 * 7]
            media_data["nextTimeStamp"] = self.timestamp + deltas[media_id % len(deltas)]
        assert media_id in map(lambda x: x["id"], self.get_media_list())
        if media_id == 1:
            self.update_chapter_data(media_data, id=1, title="Chapter1", number=1, date="2020-07-08", premium=self.has_login()),
            self.update_chapter_data(media_data, id=2, title="Chapter2", number=2, date="2020-07-09", premium=self.has_login()),
            self.update_chapter_data(media_data, id=3, title="Chapter3", number=3, date="2020-07-10", premium=self.has_login())
        elif media_id == 2:
            self.update_chapter_data(media_data, id=1, title="Chapter1", number=1),
            self.update_chapter_data(media_data, id=2, title="Chapter1-1", number="1-1"),
            self.update_chapter_data(media_data, id=6, title="Chapter1.2", number="1.2"),
            self.update_chapter_data(media_data, id=7, title="Chapter10", number="10"),
            self.update_chapter_data(media_data, id=8, title="Chapter11", number="11"),
            self.update_chapter_data(media_data, id=9, title="Chapter10.5", number="10.5"),
            self.update_chapter_data(media_data, id=10, title="Chapter100", number="100"),
            self.update_chapter_data(media_data, id=11, title="Chapter1000", number="1000"),
            self.update_chapter_data(media_data, id=12, title="Chapter9999", number="9999", premium=self.has_login()),
        elif media_id == 3:
            self.update_chapter_data(media_data, id=1, title="Chapter1", number=1, date="2020-07-08"),
            self.update_chapter_data(media_data, id=2, title="Chapter2", number=1.5, date="2020-07-08"),
            self.update_chapter_data(media_data, id=23, title="Chapter3", number=2, date="2020-07-08", premium=self.has_login()),
            self.update_chapter_data(media_data, id=24, title="Chapter4", number=3, date="2020-07-08", premium=self.has_login()),
        elif media_id == 4:
            self.update_chapter_data(media_data, id=1, title="Chapter1", number=2, date="1998-08-10"),
            self.update_chapter_data(media_data, id=2, title="Chapter1", number="1b", date="1998-08-10"),
            self.update_chapter_data(media_data, id=26, title="ChapterSpecial", number=None, date="1998-08-10"),
            self.update_chapter_data(media_data, id=27, title="Chapter0.5", number=0.5, date="1998-08-10", special=True),
            self.update_chapter_data(media_data, id=28, title="Chapter4", number=4, date="1998-08-10", inaccessible=self.inaccessible),
        else:
            self.update_chapter_data(media_data, id=1, title="Chapter1", number=1)
        for chapter_data in media_data["chapters"].values():
            chapter_data["number"] += self.offset_chapter_num

    def get_media_chapter_data(self, media_data, chapter_data, stream_index=0):
        self.maybe_inject_error()
        if self.media_type == MediaType.ANIME:
            return super().get_media_chapter_data(media_data, chapter_data, stream_index)
        return [self.create_page_data(url=f"https://some_url.com/{chapter_data['id']}.text") for k in range(3)]

    def save_chapter_page(self, page_data, path):
        self.maybe_inject_error()
        assert not os.path.exists(path)
        open(path, "w").close()


class TestServerLogin(TestServer):
    id = "test_server_login"
    counter = 0
    premium_account = True
    error_login = False
    synchronize_chapter_downloads = True

    def needs_authentication(self):
        if self.error_login:
            raise HTTPError()
        return super().needs_authentication()

    def login(self, username, password):
        self.counter += 1
        if self.error_login:
            raise HTTPError()
        self.is_premium = self.premium_account
        return True

    def reset(self):
        self.counter = 0
        self._is_logged_in = False


class TestAnimeServer(TestServer):
    id = "test_server_anime"
    media_type = MediaType.ANIME
    stream_urls = None

    def get_stream_urls(self, media_data=None, chapter_data=None):
        assert isinstance(media_data, dict) if media_data else True
        assert isinstance(chapter_data, dict) if chapter_data else True
        base_url = f"https://{self.domain}/{media_data['id']}/{chapter_data['id']}"
        return self.stream_urls or [[f"{base_url}/url.mp4?key=1&false"], [f"{base_url}/url.ts?key=1&false", f"{base_url}/url.ts?key=2&false"], ]

    def session_get(self, url, **kwargs):
        if "subtitles" in url:
            return self.subtitle_response()
        return super().session_get(url, **kwargs)

    def get_subtitle_info(self, media_data, chapter_data):
        url = "subtitles.vtt"
        alt_url = "subtitles"
        yield media_data["lang"], url, None, True, 0
        yield media_data["lang"], alt_url, None, True, 0
        yield media_data["lang"], url, "vtt", True, 0
        yield "en", url, "a", True, 0
        yield "en", url, "b", True, +5
        yield "en", url, "c", False, +5
        yield "en", url, "txt", False, 0
        yield "unknown_lang", url, "txt", False, 0

    def subtitle_response(self):
        class FakeRequest():
            text = """
WEBVTT
X-TIMESTAMP-MAP=MPEGTS:133508,LOCAL:00:00:00.000



Subtitle-C1_1
00:02:10.000 --> 00:02:12.375 line:84%
<c.Subtitle-C1_1>Universal Calendar 745,</c>

Subtitle-C2_1
00:02:12.375 --> 00:02:15.708 line:84%
<c.Subtitle-C2_1>Reich Calendar 436, December 4th:</c>

Subtitle-C3_1
00:02:16.208 --> 00:02:19.208 line:84%
<c.Subtitle-C3_1>The two great military powers of humanity</c>

Subtitle-C4_1
00:02:19.208 --> 00:02:22.708 line:77%
<c.Subtitle-C4_1>had deployed a large number of forces</c>

Subtitle-C4_2
00:02:19.209 --> 00:02:22.708 line:84%
<c.Subtitle-C4_2>in the Tiamat Stellar Region.</c>

Subtitle-C5_1
00:02:25.666 --> 00:02:30.666 line:77%
<c.Subtitle-C5_1>In this battle, the line-up of high-level commanders</c>

Subtitle-C5_2
00:02:25.667 --> 00:02:30.666 line:84%
<c.Subtitle-C5_2>for the Alliance forces was as follows:</c>
"""
            content = text.encode("utf-8")
        return FakeRequest()


class TestServerLoginAnime(TestAnimeServer, TestServerLogin):
    id = "test_server_login_anime"

    def get_stream_urls(self, media_data=None, chapter_data=None):
        if not self._is_logged_in:
            raise KeyError("missing key")
        return super().get_stream_urls(media_data, chapter_data)


class TestUnofficialServer(TestAnimeServer):
    id = "test_unofficial_server"
    official = False
    media_type = MediaType.ANIME | MediaType.NOVEL | MediaType.MANGA


class TestNovel(TestServer):
    id = "test_server_novel"
    media_type = MediaType.NOVEL
    progress_type = ProgressType.CHAPTER_VOLUME

    def update_chapter_data(self, media_data, **kwargs):
        super().update_chapter_data(media_data, volume_number=1, **kwargs)
