import json
import os
import re
import time

from requests.exceptions import ConnectionError, HTTPError, SSLError
from requests.packages import urllib3
from threading import Lock
from urllib3.exceptions import InsecureRequestWarning
import logging

from .job import Job
from .state import ChapterData, MediaData
from .util.media_type import MediaType
from .util.name_parser import (find_media_with_similar_name_in_list, get_alt_names)
from .util.progress_type import ProgressType

urllib3.disable_warnings(category=InsecureRequestWarning)


class RequestsClient():
    def __init__(self, session):
        self.session = session

    def download(self, uri, timeout=None, headers={}, verify_ssl=True):
        r = self.session.get(uri, timeout=timeout)
        return r.text, r.url


class RequestServer:

    session = None
    settings = None

    # If true a cloudscraper object should be given instead of a normal session
    need_cloud_scraper = False
    maybe_need_cloud_scraper = False
    _normal_session = None  # the normal session in case a wrapper is used
    domain = None
    implict_referer = True

    def __init__(self, session, settings=None):
        self.settings = settings
        self._normal_session = session
        if self.settings.get_always_use_cloudscraper(self.id) or self.need_cloud_scraper:
            self.session = self.get_cloudscraper_session(session)
        else:
            self.session = session
        self._lock = Lock()
        self.mem_cache = {}
        self.logger = logging.getLogger(self.id)

    def get_cloudscraper_session(self, session):
        import cloudscraper
        if getattr(RequestServer, "cloudscraper", None) is None:
            RequestServer.cloudscraper = cloudscraper.create_scraper(session, browser={
                'browser': 'firefox',
                'platform': 'linux',
                'desktop': True
            })
        return RequestServer.cloudscraper

    @classmethod
    def get_instances(clazz, session, settings=None):
        return [clazz(session, settings)]

    def update_default_args(self, kwargs):
        pass

    def backoff(self, c, r, backfactor=None):
        b = backfactor or self.settings.get_backoff_factor(self.id)
        self.logger.info(f"Sleeping for {b**c} seconds after seeing {c} failures")
        time.sleep(b**c)

    def _request(self, post_request, url, force_cloud_scraper=False, start=0, **kwargs):
        self.logger.info("Making %s request to %s ", "POST" if post_request else "GET", url)
        self.logger.debug("Request args: %s ", kwargs)
        start = start or time.time()
        if "verify" not in kwargs and self.settings.get_disable_ssl_verification(self.id):
            kwargs["verify"] = False
        if self.implict_referer and "headers" not in kwargs:
            kwargs["headers"] = {"Referer": f"https://{self.domain}"}
        self.update_default_args(kwargs)
        session = self.session
        if not kwargs.get("verify", True):
            session = self._normal_session
        elif force_cloud_scraper:
            session = self.get_cloudscraper_session(self.session)
        for i in range(self.settings.get_max_retries(self.id)):
            try:
                r = session.post(url, **kwargs) if post_request else session.get(url, **kwargs)
                if r.status_code != 200:
                    self.logger.warning("HTTPError: %d; Session class %s; headers %s;", r.status_code, type(session), kwargs.get("headers", {}))
                    self.logger.debug("HTTPError: %d; %s", r.status_code, r.text[:256])
                if not r.status_code in self.settings.status_to_retry:
                    break
                self.backoff(i + 1, r)
            except SSLError:
                if self.settings.get_fallback_to_insecure_connection(self.id) and kwargs.get("verify", True):
                    self.logger.warning("Retry request insecurely %s", url)
                    if self.settings.get_always_use_cloudscraper(self.id) or self.need_cloud_scraper:   # pragma: no cover
                        self.logger.warning("Using insecure connections and cloudscraper are not supported and may result in an error like 'ValueError: Cannot set verify_mode to CERT_NONE when check_hostname is enabled.'")
                    kwargs["verify"] = False
                    return self._request(post_request, url, **kwargs)
                raise
            except ConnectionError as e:
                self.logger.warning("ConnectionError: %s Session class %s", str(e), type(session))
                if i == self.settings.get_max_retries(self.id) - 1:
                    raise
                continue
        if self.maybe_need_cloud_scraper and not force_cloud_scraper and r.status_code in (403, 503):
            if session == self._normal_session:
                return self._request(post_request, url, force_cloud_scraper=True, **kwargs)
        r.raise_for_status()
        end = time.time()

        if end - start > 1:
            self.logger.info("Took %ds to make request to %s", end - start, url)
        return r

    def session_get(self, url, post=False, **kwargs):
        return self._request(post, url, **kwargs)

    def get_redirect_url(self, url, post=False, **kwargs):
        return self._request(post, url, **kwargs).url

    def session_post(self, url, **kwargs):
        return self._request(True, url, **kwargs)

    def session_get_cookie(self, name):
        assert self.domain
        for cookie in self.session.cookies:
            if cookie.name == name and (self.domain in cookie.domain or cookie.domain in self.domain):
                return cookie.value
        return None

    def session_get_cache(self, url, key=None, mem_cache=False, skip_cache=False, ttl=7, use_json=False, output_format_func=None, **kwargs):
        if skip_cache:
            return self.session_get(url, **kwargs).json()
        _data = kwargs.get("data", kwargs.get("json", ""))
        key = (key or url) + (str(hash(json.dumps(_data))) if _data else "")
        file = self.settings.get_web_cache(key)
        if key in self.mem_cache:
            return self.mem_cache[key]
        if not mem_cache:
            try:
                if ttl < 0 or time.time() - os.path.getmtime(file) < ttl * 3600 * 24:
                    with open(file, "r") as f:
                        self.logger.debug("Returning cached value for %s", url)
                        return json.load(f) if use_json else f.read()
                else:
                    os.remove(file)
            except (json.decoder.JSONDecodeError, FileNotFoundError):
                pass
        r = self.session_get(url, **kwargs)
        text = output_format_func(r.text) if output_format_func else r.text
        data = json.loads(text) if use_json else text

        if mem_cache:
            self.mem_cache[key] = data
        elif ttl:
            for i in range(2):
                try:
                    with open(file, "w") as f:
                        f.write(text)
                        break
                except FileNotFoundError:
                    os.makedirs(self.settings.get_web_cache_dir(), exist_ok=True)
        return data

    def session_get_cache_json(self, url, **kwargs):
        return self.session_get_cache(url, use_json=True, **kwargs)

    def soupify(self, BeautifulSoup, r):
        return BeautifulSoup(r if isinstance(r, str) else r.text, self.settings.bs4_parser)

    def get_extension(self, url):
        _, ext = os.path.splitext(url.split("?")[0])
        if ext and ext[0] == ".":
            ext = ext[1:]
        return ext


class MediaServer(RequestServer):
    remove_lang_regex = re.compile(r" \([^)]*\)")
    non_word_char_regex = re.compile(r"\W+")

    # If true, always just search the literal title instead of also searching subsections
    fuzzy_search = False

    need_to_login_to_list = False

    version = 0

    def maybe_relogin(self):
        with self._lock:
            if self.need_to_login_to_list and self.needs_to_login():
                self.logger.info("Server is not authenticated; relogging in")
                if not self.relogin():
                    raise ValueError("Failed to login")

    def list_media(self, limit=None):
        self.maybe_relogin()

        return list(self.get_media_list(limit=limit))

    def update(self, media_data):
        self.maybe_relogin()
        self.update_media_data(media_data)

    def score_results(self, term_parts, media_name):
        media_name = self.remove_lang_regex.sub("", media_name)
        parts = set(self.non_word_char_regex.split(media_name.lower()))
        return -2 * len(parts.intersection(term_parts)) / (len(parts) + len(term_parts))

    def search(self, term, media_type=None, literal=False, limit=20):
        """
        Searches for a media containing term
        Different servers will handle search differently. Some are very literal while others do prefix matching and some would match any word
        """
        terms = get_alt_names(term) if not literal and not self.fuzzy_search else [term]
        media_list = self.search_helper(terms, limit, media_type=media_type)

        term_parts = set(self.non_word_char_regex.split(term.lower()))
        return list(map(lambda x: (self.score_results(term_parts=term_parts, media_name=x["name"]), x), filter(lambda x: not media_type or x["media_type"] & media_type, media_list)))

    def search_helper(self, terms, limit=None, media_type=None, **kwargs):
        self.maybe_relogin()
        media_map = {}
        for term in terms:
            for media_data in self.search_for_media(term, limit=limit, media_type=media_type, **kwargs):
                media_map[media_data.global_id] = media_data
            if limit and len(media_map) >= limit:
                break
        return media_map.values()

    def create_media_data(self, id, name, season_id=None, season_title="", dir_name=None, offset=0, alt_id=None, progress_type=None, lang="", media_type=None, **kwargs):
        season_title = season_title or ""
        if not lang:
            match = re.search(r"\((\w*) Dub\)", name) or re.search(r"\((\w*) Dub\)", season_title)
            if match:
                lang = match.group(1) if match else ""
            else:
                match = re.search(r"\(Dub\)", name) or re.search(r"\(Dub\)", season_title)
                lang = "dub" if match else ""
        if media_type is None:
            media_type = self.media_type

        return MediaData(dict(server_id=self.id, server_alias=self.alias, id=id, dir_name=dir_name if dir_name else re.sub(r"[\W]", "", name.replace(" ", "_")), name=name, media_type=media_type.value, media_type_name=media_type.name, progress=0, season_id=season_id, season_title=season_title, offset=offset, alt_id=alt_id, trackers={}, progress_type=progress_type if progress_type is not None else self.progress_type, tags=[], lang=lang, nextTimeStamp=0, official=self.official, version=self.version, **kwargs))

    def update_chapter_data(self, media_data, id, title, number, volume_number=None, premium=False, alt_id=None, special=False, date=None, subtitles=None, inaccessible=False, **kwargs):
        if number is None or number == "" or isinstance(number, str) and number.isalpha():
            number = 0
            special = True
        id = str(id)
        if isinstance(number, str):
            try:
                number = float(number.replace("-", "."))
            except ValueError:
                special = True
                number = float(re.search("\d+", number).group(0))
        if media_data["offset"]:
            number = round(number - media_data["offset"], 4)
        if number % 1 == 0:
            number = int(number)

        new_values = dict(id=id, title=title, number=number, volume_number=volume_number, premium=premium, alt_id=alt_id, special=special, date=date, subtitles=subtitles, inaccessible=inaccessible, **kwargs)
        if id in media_data["chapters"]:
            media_data["chapters"][id].update(new_values)
        else:
            media_data["chapters"][id] = ChapterData(new_values)
            media_data["chapters"][id]["read"] = False

        chapter_data = media_data["chapters"][id]
        chapter_dir_name = self.settings.get_chapter_dir_name(media_data, chapter_data)
        if not chapter_data.get("dir_name") or chapter_dir_name != chapter_data.get("dir_name") and not os.path.exists(self.settings.get_chapter_dir(media_data, chapter_data, skip_create=True)):
            chapter_data["dir_name"] = chapter_dir_name

        return True

    def create_page_data(self, url, id=None, encryption_key=None, ext=None, headers={}):
        if not ext:
            ext = self.get_extension(url)
        return dict(url=url, id=id, encryption_key=encryption_key, ext=ext, headers=headers)


class GenericServer(MediaServer):
    """
    This class is intended to separate the overridable methods of Server from
    the internal business logic.

    Servers need not override most of the methods of this. Some have default
    values that are sane in some common situations
    """
    # Unique id of the server
    id = None
    # If set this value will be used for credential lookup instead of id
    alias = None
    media_type = MediaType.MANGA
    torrent = False
    # Regex to match to determine if this server can stream a given url.
    # It is also used to determine if server can add the media based on its chapter url
    stream_url_regex = None
    # Regex to match to determine if we can add this series by the matching url
    # Note that if this value is non-None then so must stream_url_regex
    add_series_url_regex = None
    # Measures progress in volumes instead of chapter/episodes
    progress_type = ProgressType.CHAPTER_ONLY
    # True if the server only provides properly licensed media
    official = True
    # If the server has some free media (used for testing)
    has_free_chapters = True
    # Used to determine if the account can access premium content
    is_premium = False
    # Used to indicate that the download feature for the server is slow (for testing)
    slow_download = False

    def get_media_list(self, limit=None):  # pragma: no cover
        """
        Returns an arbitrary selection of media.
        """
        raise NotImplementedError

    def search_for_media(self, term, limit=None, media_type=None, **kwargs):
        """
        Searches for a media containing term
        Different servers will handle search differently. Some are very literal while others do prefix matching and some would match any word
        """
        return find_media_with_similar_name_in_list(get_alt_names(term), self.get_media_list())

    @property
    def fuzzy_search(self):
        return self.search_for_media == GenericServer.search_for_media

    def update_media_data(self, media_data):  # pragma: no cover
        """
        Returns media data from API
        """
        raise NotImplementedError

    def get_media_chapter_data(self, media_data, chapter_data, stream_index=0):
        """
        Returns a list of page/episode data. For anime (specifically for video files) this may be a list of size 1
        The default implementation is for anime servers and will contain the preferred stream url
        """
        last_err = None
        urls = self.maybe_login_and_get_stream_urls(media_data=media_data, chapter_data=chapter_data)

        self.logger.debug("Stream urls %s", urls)
        if stream_index != 0:
            urls = urls[stream_index:] + urls[:stream_index]

        for stream_url in urls:
            page_data = []
            for url in stream_url:
                ext = self.get_extension(url)
                try:
                    if ext == "m3u8":
                        segments = self.get_m3u8_segments(url)
                        page_data.extend([self.create_page_data(url=segment.uri, encryption_key=segment.key, ext="ts") for segment in segments])
                    else:
                        page_data.extend([self.create_page_data(url=url, ext=ext)])
                except ImportError as e:
                    last_err = e
            if page_data:
                return page_data

        raise last_err

    def save_chapter_page(self, page_data, path):
        """ Save the page designated by page_data to path
        By default it blindly writes the specified url to disk, decrypting it
        if needed.
        """
        r = self.session_get(page_data["url"], headers=page_data["headers"])
        content = r.content
        key = page_data["encryption_key"]
        if key:
            from Crypto.Cipher import AES
            key_bytes = self.session_get(key.uri, headers=page_data["headers"]).content
            iv = int(key.iv, 16).to_bytes(16, "big") if key.iv else None
            content = AES.new(key_bytes, AES.MODE_CBC, iv).decrypt(content)
        with open(path, 'wb') as fp:
            fp.write(content)

    def get_related_media_seasons(self, media_data):
        """ Returns all related seasons of media_data
        """
        return [media_data]

    def _get_media_id_from_url(self, url):
        """ Helper method to get the media_id from the url
        This method should be treated as "protected" and not called by outside classes
        as it may give nonsensical values
        """
        return (self.stream_url_regex.search(url) or self.add_series_url_regex.search(url)).group(1)

    def get_media_data_from_url(self, url):  # pragma: no cover
        """ Return the media data related to this url

        url should be the page needed to view the episode/chapter.
        The protocol, query parameters or presence of "www" should be ignored.
        The media does not need to have its chapter's list populated but it is
        allowed to.
        """
        raise NotImplementedError

    def get_chapter_id_for_url(self, url):  # pragma: no cover
        """ Return the chapter id related to this url
        Like get_media_data_from_url but returns just the chapter id
        """
        raise NotImplementedError

    def can_stream_url(self, url):
        return self.stream_url_regex and self.stream_url_regex.search(url)

    def can_add_media_from_url(self, url):
        return self.can_stream_url(url) or self.add_series_url_regex and self.add_series_url_regex.search(url)

    ################ ANIME ONLY #####################
    def get_stream_url(self, media_data, chapter_data, stream_index=0):
        """ Returns a url to stream from
        Override get_stream_urls instead
        """

        return self.prepare_stream(media_data=media_data, chapter_data=chapter_data,
                                   urls=self.maybe_login_and_get_stream_urls(media_data=media_data, chapter_data=chapter_data)[stream_index])

    def prepare_stream(self, media_data, chapter_data, urls):
        return urls

    def maybe_login_and_get_stream_urls(self, media_data, chapter_data):
        def func(): return list(self.get_stream_urls(media_data=media_data, chapter_data=chapter_data))
        return self.relogin_on_error(func)

    def get_stream_urls(self, media_data, chapter_data):  # pragma: no cover
        raise NotImplementedError

    def get_m3u8_info(self, url):
        import m3u8
        return m3u8.load(url, http_client=RequestsClient(self.session))

    def get_m3u8_segments(self, url):
        m = self.get_m3u8_info(url)
        if not m.segments:
            playlist = sorted(m.playlists, key=lambda x: x.stream_info.bandwidth, reverse=True)
            m = self.get_m3u8_info(playlist[0].uri)
        assert m.segments
        return m.segments

    def download_subtitles(self, media_data, chapter_data):
        """ Only for ANIME, Download subtitles to dir_path
        By default does nothing. Subtitles should generally have the same name
        as the final media
        """

        sub_dir = None
        subtitle_regex = re.compile(r"\w*-\w\d*_[2-9]\d*$")
        for lang, url, ext, flip in self.get_subtitle_info(media_data, chapter_data):
            if not ext:
                ext = self.get_extension(url)
            basename = self.settings.get_page_file_name(media_data, chapter_data, ext=ext)
            if not sub_dir:
                sub_dir = self.settings.get_subtitles_dir(media_data, chapter_data)
                os.makedirs(sub_dir, exist_ok=True)
            path = os.path.join(sub_dir, basename)
            if not os.path.exists(path):
                r = self.session_get(url)
                if flip:
                    with open(path, 'w') as fp:
                        iterable = iter(r.content.decode().splitlines())
                        buffer = None
                        for line in iterable:
                            # 00:02:04.583 --> 00:02:13.250 line:84%
                            if subtitle_regex.match(line):
                                buffer = None  # ignore blank line
                                # don't output this line
                                next(iterable)  # skip line with timestamp
                            else:
                                if buffer is not None:
                                    fp.write(f"{buffer}\n")
                                buffer = line
                        fp.write(f"{buffer}\n")
                else:
                    with open(path, "wb") as fp:
                        fp.write(r.content)

    def get_subtitle_info(self, media_data, chapter_data):   # pragma: no cover
        """
        Yeilds lang, url, ext, flip
        lang - the language of the subtiles. If the language is permitted for this media, the entry will be skipped
        url - the url to download the subtitles
        ext - ext of the subtitles or None if we should auto detect by url
        flip - whether we need to fix broken subtitle formats that invert mutli-line subs
        """
        # Empty generator
        return
        yield

    ################ Needed for servers requiring logins #####################

    def needs_authentication(self):
        """
        Checks if the user is logged in

        If the user is not logged in (and needs to login to access all content),
        this method should return true.
        """
        return self.has_login() and not self.is_logged_in

    def login(self, username, password):  # pragma: no cover
        """ Used the specified username/passowrd to authenticate

        This method should return True iff login succeeded even if the account isn't premium
        Set `is_premium` if the account is premium.
        If it is perfectly fine to throw an HTTPError on failed authentication.
        """
        raise NotImplementedError

    ################ OPTIONAL #####################

    def post_download(self, media_data, chapter_data, page_paths):
        """ Runs after all pages have been downloaded
        """
        pass


class Server(GenericServer):
    """
    The methods contained in this class should rarely be overridden
    """

    _is_logged_in = False
    DOWNLOAD_MARKER = ".downloaded"

    @property
    def is_logged_in(self):
        return self._is_logged_in

    def has_login(self):
        return self.login.__func__ is not GenericServer.login

    def is_local_server(self):
        return self.download_chapter.__func__ is not Server.download_chapter

    def get_credentials(self):
        return self.settings.get_credentials(self.id if not self.alias else self.alias)

    def relogin(self):
        username, password = self.get_credentials()
        try:
            self._is_logged_in = self.login(username, password)
        except HTTPError:
            self._is_logged_in = False
        if not self._is_logged_in:
            self.logger.warning("Could not login with username: %s", username)
        else:
            self.logger.info("Logged into %s; premium %s", self.id, self.is_premium)
        return self._is_logged_in

    def get_download_marker(self, media_data, chapter_data):
        dir_path = self.settings.get_chapter_dir(media_data, chapter_data)
        return os.path.join(dir_path, self.DOWNLOAD_MARKER)

    def is_fully_downloaded(self, media_data, chapter_data):
        return os.path.exists(self.get_download_marker(media_data, chapter_data))

    def mark_download_complete(self, media_data, chapter_data):
        open(self.get_download_marker(media_data, chapter_data), 'w').close()

    def download_if_missing(self, page_data, full_path):
        if os.path.exists(full_path):
            self.logger.debug("Page %s already download", full_path)
        else:
            self.logger.info("downloading %s", full_path)
            temp_path = os.path.join(os.path.dirname(full_path), ".tmp-" + os.path.basename(full_path))
            self.save_chapter_page(page_data, temp_path)
            os.rename(temp_path, full_path)

    def get_children(self, media_data, chapter_data):
        dir_path = self.settings.get_chapter_dir(media_data, chapter_data, skip_create=True)
        return sorted(map(lambda x: os.path.join(dir_path, x), filter(lambda x: x[0] != ".", os.listdir(dir_path))))

    def relogin_on_error(self, func):
        try:
            return func()
        except KeyError as e:
            if self.needs_to_login():
                self.logger.debug("Failed to get media info; relogging in and retrying", str(e))
                self.relogin()
                return func()
            else:  # pragma: no cover
                self.logger.error("Error %s: This could happen if you are trying to view mature account and are being blocked, or if you are trying to consume premium content without a premium account", str(e))
                raise

    def needs_to_login(self):
        try:
            return not self.is_logged_in and self.needs_authentication()
        except HTTPError:
            return True

    def pre_download(self, media_data, chapter_data):
        if chapter_data["inaccessible"]:
            self.logger.info("Chapter is not accessible")
            raise ValueError("Cannot access chapter")
        if chapter_data["premium"] and not self.is_premium:
            if self.needs_to_login():
                self.logger.info("Server is not authenticated; relogging in")
                if not self.relogin():
                    self.logger.info("Cannot access chapter %s #%s %s", media_data["name"], str(chapter_data["number"]), chapter_data["title"])
            else:
                self._is_logged_in = True
            if not self.is_premium:
                self.logger.info("Cannot access chapter %s #%s %s because account is not premium", media_data["name"], str(chapter_data["number"]), chapter_data["title"])
                raise ValueError("Cannot access premium chapter")

        if self.media_type == MediaType.ANIME:
            def func(): self.download_subtitles(media_data, chapter_data)
            self.relogin_on_error(func)

    def download_chapter(self, media_data, chapter_data, **kwargs):
        if self.is_fully_downloaded(media_data, chapter_data):
            self.logger.info("Already downloaded %s %s", media_data["name"], chapter_data["title"])
            return False

        dir_path = self.settings.get_chapter_dir(media_data, chapter_data)
        os.makedirs(dir_path, exist_ok=True)
        with self._lock:
            self.logger.info("Starting download of %s %s", media_data["name"], chapter_data["title"])
            self.pre_download(media_data, chapter_data)
            page_paths = self.download_pages(media_data, chapter_data, **kwargs)
            self.post_download(media_data, chapter_data, page_paths=page_paths)

        self.settings.post_process(media_data, page_paths, self.settings.get_media_dir(media_data))

        self.mark_download_complete(media_data, chapter_data)
        self.logger.info("%s %d %s is downloaded; Total pages %d", media_data["name"], chapter_data["number"], chapter_data["title"], len(page_paths))

        return True

    def download_pages(self, media_data, chapter_data, page_limit=None, offset=0, stream_index=0):
        list_of_pages = []
        dir_path = self.settings.get_chapter_dir(media_data, chapter_data)
        # download pages
        job = Job(self.settings.get_threads(media_data), raiseException=True)
        for i, page_data in enumerate(self.get_media_chapter_data(media_data, chapter_data, stream_index=stream_index)):
            if page_limit is not None and i == page_limit:
                break
            if i >= offset:
                list_of_pages.append(page_data)
                page_data["path"] = os.path.join(dir_path, self.settings.get_page_file_name(media_data, chapter_data, ext=page_data["ext"], page_number=i))
                job.add(lambda page_data=page_data: self.download_if_missing(page_data, page_data["path"]))
        job.run()
        assert list_of_pages
        return [page_data["path"] for page_data in list_of_pages]

    def has_chapter_limit(self):
        return self.get_remaining_chapters.__func__ is not Server.get_remaining_chapters

    def get_remaining_chapters(self, media_data):
        """ Number of chapters of the given media that can be downloaded right now
        Some servers will only let one download X chapters per time period, so this method
        provides a way to query how many more chapters can be obtained. Note that while we check
        for a specific media, the limit is often global.

        This method should only be called if the user is logged in.
        """
        return float("inf"), 0


class Tracker(RequestServer):
    id = None
    official = True
    alias = None

    def get_media_dict(self, id, media_type, name, progress, progress_volumes=None, score=0, nextTimeStamp=None, time_spent=0, year=0, year_end=0, season=None, genres=tuple(), tags=tuple(), studio=tuple(), external_links=tuple(), streaming_links=tuple()):
        m = dict(locals())
        del m["self"]
        return m

    def get_auth_url(self):  # pragma: no cover
        """ Return the url the user can goto to get the auth token"""
        raise NotImplementedError

    def update(self, list_of_updates):  # pragma: no cover
        """ Updates progress to remote tracker
        list_of_updates is a list of tuples -- tracker_id, progress, progress_volumes
        where progress is the numerical value to update to and progress_volumes is
        whether to treat this a chapter/episode progress or volume progress
        """
        raise NotImplementedError

    def get_full_list_data(self, user_name=None, id=None):
        return self.get_tracker_list(user_name, id, status=None)

    def get_tracker_list(self, user_name=None, id=None, status="CURRENT"):  # pragma: no cover
        """ Returns a list of media dicts
        See get_media_dict
        """
        raise NotImplementedError
