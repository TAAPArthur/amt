import logging
import os
import re
from functools import cache
from threading import Lock

from requests.exceptions import HTTPError

from .job import Job
from .state import ChapterData, MediaData
from .util.media_type import MediaType
from .util.name_parser import (find_media_with_similar_name_in_list,
                               get_alt_names)


def get_extension(url):
    _, ext = os.path.splitext(url.split("?")[0])
    if ext and ext[0] == ".":
        ext = ext[1:]
    return ext


class RequestServer:

    session = None
    settings = None

    # If true a cloudscraper object should be given instead of a normal session
    need_cloud_scraper = False

    def __init__(self, session, settings=None):
        self.settings = settings
        if self.need_cloud_scraper:
            import cloudscraper
            if getattr(RequestServer, "cloudscraper", None) is None:
                RequestServer.cloudscraper = cloudscraper.create_scraper(browser={
                    'browser': 'firefox',
                    'platform': 'linux',
                    'desktop': True
                })
                RequestServer.cloudscraper.cookies = session.cookies
            self.session = RequestServer.cloudscraper
        else:
            self.session = session
        self._lock = Lock()

    @classmethod
    def get_instances(clazz, session, settings=None):
        return [clazz(session, settings)]

    def _request(self, get, url, **kwargs):
        logging.info("Making %s request to %s ", "GET" if get else "POST", url)
        logging.debug("Request args: %s ", kwargs)
        kwargs["verify"] = not self.settings.get_disable_ssl_verification(self.id)
        r = self.session.get(url, **kwargs) if get else self.session.post(url, **kwargs)
        if r.status_code != 200:
            logging.warning("HTTP Error: %d", r.status_code)
        r.raise_for_status()
        return r

    def session_get_cookie(self, name, domain=None):
        for cookie in self.session.cookies:
            if cookie.name == name and (domain in cookie.domain or cookie.domain in domain):
                return cookie.value
        return None

    @cache
    def session_get_mem_cache(self, url, **kwargs):
        return self.session_get(url, **kwargs)

    def session_get(self, url, **kwargs):
        return self._request(True, url, **kwargs)

    def session_post(self, url, **kwargs):
        return self._request(False, url, **kwargs)

    def soupify(self, BeautifulSoup, r):
        return BeautifulSoup(r.text, self.settings.bs4_parser)


class MediaServer(RequestServer):
    def create_media_data(self, id, name, season_id=None, season_title="", dir_name=None, offset=0, alt_id=None, progress_volumes=None, **kwargs):
        return MediaData(dict(server_id=self.id, id=id, dir_name=dir_name if dir_name else re.sub(r"[\W]", "", name.replace(" ", "_")), name=name, media_type=self.media_type.value, media_type_name=self.media_type.name, progress=0, season_id=season_id, season_title=season_title, offset=offset, alt_id=alt_id, trackers={}, progress_volumes=progress_volumes if progress_volumes is not None else self.progress_volumes, tags=[], **kwargs))

    def update_chapter_data(self, media_data, id, title, number, premium=False, alt_id=None, special=False, date=None, subtitles=None, inaccessible=False, **kwargs):
        if number is None or number == "" or isinstance(number, str) and number.isalpha():
            return
        id = str(id)
        if isinstance(number, str):
            try:
                number = int(number)
            except ValueError:
                special = True
                number = float(number.replace("-", "."))
        if media_data["offset"]:
            number = round(number - media_data["offset"], 4)
        if number % 1 == 0:
            number = int(number)

        new_values = dict(id=id, title=title, number=number, premium=premium, alt_id=alt_id, special=special, date=date, subtitles=subtitles, inaccessible=inaccessible, **kwargs)
        if id in media_data["chapters"]:
            media_data["chapters"][id].update(new_values)
        else:
            media_data["chapters"][id] = ChapterData(new_values)
            media_data["chapters"][id]["read"] = False
        return True

    def create_page_data(self, url, id=None, encryption_key=None, ext=None):
        if not ext:
            ext = get_extension(url)
        assert ext, url
        return dict(url=url, id=id, encryption_key=encryption_key, ext=ext)


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
    # Pattern to match to determine if this server can stream a given url.
    # It is also used to determine if server can add the media based on its chapter url
    stream_url_regex = None
    # Measures progress in volumes instead of chapter/episodes
    progress_volumes = False
    # True if the server only provides properly licensed media
    official = True
    # Download a single page from this server at a time
    synchronize_chapter_downloads = False
    # If the server has some free media (used for testing)
    has_free_chapters = True
    # Used to determine if the account can access premium content
    is_premium = False

    def get_media_list(self, limit=None):  # pragma: no cover
        """
        Returns an arbitrary selection of media.
        """
        raise NotImplementedError

    def search(self, term, limit=None):
        """
        Searches for a media containing term
        Different servers will handle search differently. Some are very literal while others do prefix matching and some would match any word
        """
        return list(find_media_with_similar_name_in_list(get_alt_names(term), self.get_media_list(limit=limit)))

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
        urls = self.get_stream_urls(media_data=media_data, chapter_data=chapter_data)

        logging.debug("Stream urls %s", urls)
        if stream_index != 0:
            urls = urls[stream_index:] + urls[:stream_index]

        for url in urls:
            ext = get_extension(url)
            try:
                if ext == "m3u8":
                    import m3u8
                    m = m3u8.load(url)
                    if not m.segments:
                        playlist = sorted(m.playlists, key=lambda x: x.stream_info.bandwidth, reverse=True)
                        m = m3u8.load(playlist[0].uri)
                    assert m.segments
                    return [self.create_page_data(url=segment.uri, encryption_key=segment.key, ext="ts") for segment in m.segments]
                else:
                    return [self.create_page_data(url=url, ext=ext)]
            except ImportError as e:
                last_err = e
        raise last_err

    def save_chapter_page(self, page_data, path):
        """ Save the page designated by page_data to path
        By default it blindly writes the specified url to disk, decrypting it
        if needed.
        """
        r = self.session_get(page_data["url"], stream=True)
        content = r.content
        key = page_data["encryption_key"]
        if key:
            from Crypto.Cipher import AES
            key_bytes = self.session_get_mem_cache(key.uri).content
            iv = int(key.iv, 16).to_bytes(16, "big") if key.iv else None
            content = AES.new(key_bytes, AES.MODE_CBC, iv).decrypt(content)
        with open(path, 'wb') as fp:
            fp.write(content)

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

    ################ ANIME ONLY #####################
    def get_stream_url(self, media_data, chapter_data, stream_index=0):
        """ Returns a url to stream from
        Override get_stream_urls instead
        """
        return list(self.get_stream_urls(media_data=media_data, chapter_data=chapter_data))[stream_index]

    def get_stream_urls(self, media_data, chapter_data):  # pragma: no cover
        raise NotImplementedError

    def download_subtitles(self, media_data, chapter_data, dir_path):
        """ Only for ANIME, Download subtitles to dir_path
        By default does nothing. Subtitles should generally have the same name
        as the final media
        """
        pass

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

    def post_download(self, media_data, chapter_data, dir_path, pages):
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
        credential = self.get_credentials()
        if credential:
            try:
                logged_in = self.login(credential[0], credential[1])
            except HTTPError:
                logged_in = False
            if not logged_in:
                logging.warning("Could not login with username: %s", credential[0])
            else:
                logging.info("Logged into %s; premium %s", self.id, self.is_premium)

            self._is_logged_in = logged_in
            return logged_in
        logging.warning("Could not load credentials")
        return False

    def is_fully_downloaded(self, media_data, chapter_data):
        dir_path = self.settings.get_chapter_dir(media_data, chapter_data)
        return os.path.exists(os.path.join(dir_path, self.DOWNLOAD_MARKER))

    def mark_download_complete(self, dir_path):
        open(os.path.join(dir_path, self.DOWNLOAD_MARKER), 'w').close()

    def download_if_missing(self, page_data, full_path):
        if os.path.exists(full_path):
            logging.debug("Page %s already download", full_path)
        else:
            logging.info("downloading %s", full_path)
            temp_path = os.path.join(os.path.dirname(full_path), ".tmp-" + os.path.basename(full_path))
            self.save_chapter_page(page_data, temp_path)
            os.rename(temp_path, full_path)

    def get_children(self, media_data, chapter_data):
        return "{}/*".format(self.settings.get_chapter_dir(media_data, chapter_data))

    def needs_to_login(self):
        try:
            return not self.is_logged_in and self.needs_authentication()
        except HTTPError:
            return True

    def pre_download(self, media_data, chapter_data):
        if chapter_data["inaccessible"]:
            logging.info("Chapter is not accessible")
            raise ValueError("Cannot access chapter")
        if chapter_data["premium"] and not self.is_premium:
            if self.needs_to_login():
                logging.info("Server is not authenticated; relogging in")
                if not self.relogin():
                    logging.info("Cannot access chapter %s #%s %s", media_data["name"], str(chapter_data["number"]), chapter_data["title"])
            else:
                self._is_logged_in = True
            if not self.is_premium:
                logging.info("Cannot access chapter %s #%s %s because account is not premium", media_data["name"], str(chapter_data["number"]), chapter_data["title"])
                raise ValueError("Cannot access premium chapter")

        if self.media_type == MediaType.ANIME:
            sub_dir = os.path.join(self.settings.get_chapter_dir(media_data, chapter_data), self.settings.subtitles_dir)
            os.makedirs(sub_dir, exist_ok=True)
            self.download_subtitles(media_data, chapter_data, dir_path=sub_dir)

    def download_chapter(self, media_data, chapter_data, page_limit=None, offset=0, stream_index=0):
        if self.is_fully_downloaded(media_data, chapter_data):
            logging.info("Already downloaded %s %s", media_data["name"], chapter_data["title"])
            return False
        try:
            if self.synchronize_chapter_downloads:
                self._lock.acquire()
            return self._download_chapter(media_data, chapter_data, page_limit, offset, stream_index)
        finally:
            if self.synchronize_chapter_downloads:
                self._lock.release()

    def _download_chapter(self, media_data, chapter_data, page_limit=None, offset=0, stream_index=0):
        logging.info("Starting download of %s %s", media_data["name"], chapter_data["title"])
        dir_path = self.settings.get_chapter_dir(media_data, chapter_data)
        os.makedirs(dir_path, exist_ok=True)
        self.pre_download(media_data, chapter_data)
        list_of_pages = []

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
        if self.media_type == MediaType.MANGA and (1 + len(list_of_pages)) % 2 == self.settings.get_force_page_parity(media_data):
            try:
                from PIL import Image
                page_number = len(list_of_pages) if self.settings.get_force_page_parity_end(media_data) else -1
                full_path = os.path.join(dir_path, self.settings.get_page_file_name(media_data, chapter_data, ext="jpg", page_number=page_number))
                image = Image.new("RGB", (1, 1))
                image.save(full_path)
            except ImportError:
                logging.warning("Need PIL to use force_page_parity")

        self.post_download(media_data, chapter_data, dir_path, list_of_pages)
        self.settings.post_process(media_data, (page_data["path"] for page_data in list_of_pages), dir_path)
        self.mark_download_complete(dir_path)
        logging.info("%s %d %s is downloaded; Total pages %d", media_data["name"], chapter_data["number"], chapter_data["title"], len(list_of_pages))

        return True


class TorrentHelper(MediaServer):
    id = None
    media_type = MediaType.ANIME
    official = False
    progress_volumes = True

    def download_torrent_file(self, media_data):
        """
        Downloads the raw torrent file
        """
        self.save_torrent_file(media_data, self.settings.get_external_downloads_path(media_data))

    def save_torrent_file(self, media_data, path):  # pragma: no cover
        """Save the torrent file to disk"""
        raise NotImplementedError


class Tracker(RequestServer):
    id = None
    official = True

    def get_media_dict(self, id, media_type, name, progress, progress_volumes=None, score=0, time_spent=0, year=0, season=None, genres=[], tags=[], studio=[]):
        return {"id": id, "media_type": media_type, "name": name, "progress": progress, "progress_volumes": progress_volumes,
                "score": score, "time_spent": time_spent, "year": year, "season": season, "genres": genres, "tags": tags, "studio": studio
                }

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
