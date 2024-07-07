from ..server import Server
from ..util import name_parser
from ..util.media_type import MediaType
from ..util.name_parser import group_titles_for_same_media_season, get_season_id
from ..util.progress_type import ProgressType
from urllib.parse import urlparse, parse_qs
import os
import re
import shutil
import tempfile


class GenericTorrentServer(Server):
    media_type = MediaType.ANIME | MediaType.NOVEL | MediaType.MANGA
    progress_type = ProgressType.VOLUME_ONLY
    official = False
    torrent = True

    parts_server = False
    version = 2

    def upgrade_state(self, media_data):
        return media_data["id"]

    @classmethod
    def get_instances(clazz, session, settings, **kwargs):
        return super().get_instances(session, settings, **kwargs) if settings.torrent_list_cmd else []

    def get_torrent_url_from_basename(self, media_data, filename):  # pragma: no cover
        return filename

    def get_abs_torrent_file_path(self, media_data, filename):
        dir_path = self.settings.get_media_dir(media_data)
        os.makedirs(dir_path, exist_ok=True)
        return os.path.join(dir_path, os.path.basename(filename))

    def list_files(self, media_data):
        dir_path = self.settings.get_media_dir(media_data)
        for torrent_file in media_data["torrent_files"]:
            abs_torrent_file_path = self.get_abs_torrent_file_path(media_data, self.get_torrent_url_from_basename(media_data, torrent_file))
            for file in self.settings.run_cmd_and_save_output(self.settings.torrent_list_cmd, media_data=media_data, env_extra={"TORRENT_FILE": abs_torrent_file_path}, wd=dir_path).splitlines():
                yield abs_torrent_file_path, file

    def search_for_media_helper(self, term=None, media_type=None, url=None):  # pragma: no cover
        raise NotImplementedError

    def search_for_media(self, term, media_type=None, url=None, **kwargs):
        results = []
        raw_search_results = self.search_for_media_helper(term, media_type=media_type, url=url)
        if not self.parts_server:
            for slug, title, mediatype, label in raw_search_results:
                results.append(self.create_media_data(id=slug, name=title, label=label, torrent_files=[slug], media_type=mediatype))
        else:
            title_media_type_list = [(title, mediatype) for _, title, mediatype, _ in raw_search_results]
            for sample_file, title, media_type, season_id in group_titles_for_same_media_season(title_media_type_list):
                lang = self.infer_lang(sample_file)
                results.append(self.create_media_data(id=title, name=title, media_type=media_type, lang=lang, season_id=season_id))

        return results

    def update_media_data(self, media_data, limit=None, **kwargs):

        if self.parts_server:
            for slug, title, mediatype, _ in self.search_for_media_helper(media_data["name"], media_type=media_data["media_type"]):
                if title.startswith(media_data["name"]) and media_data["season_id"] == get_season_id(title):
                    media_data["torrent_files"].append(slug)
            media_data["torrent_files"] = list(set(media_data["torrent_files"]))

        for torrent_file in media_data["torrent_files"][:limit]:
            self.download_torrent_file(media_data, self.get_torrent_url_from_basename(media_data, torrent_file))

        files = list(self.list_files(media_data))

        for torrent_file, file in files:
            title = os.path.basename(file)
            n = name_parser.get_number_from_file_name(file, media_name=media_data["name"])
            self.update_chapter_data(media_data, id=file, title=title, alt_id=title, number=n, path=file, torrent_file=torrent_file, special="OVA" in title.upper())

    def download_pages(self, media_data, chapter_data, **kwargs):
        dir_path = self.settings.get_media_dir(media_data)
        os.makedirs(dir_path, exist_ok=True)
        assert(os.path.exists(dir_path))
        self.settings.run_cmd(self.settings.torrent_download_cmd, media_data=media_data, chapter_data=chapter_data, wd=dir_path, raiseException=True, env_extra={"TORRENT_FILE": chapter_data["torrent_file"]})
        return [chapter_data["id"]]

    def post_download(self, media_data, chapter_data, page_paths):
        dest = os.path.join(self.settings.get_chapter_dir(media_data, chapter_data), os.path.basename(chapter_data["id"]))
        src = os.path.join(self.settings.get_media_dir(media_data), page_paths[0])
        os.symlink(src, dest)

    def get_stream_url(self, media_data, chapter_data, stream_index=0):
        return [None]

    def download_torrent_file(self, media_data, torrent_file_url):
        """
        Downloads the raw torrent file
        """

        path = self.get_abs_torrent_file_path(media_data, torrent_file_url)
        if not os.path.exists(path):
            self.logger.info("Downloading torrent file to %s", path)
            self.save_torrent_file(torrent_file_url, path)
        return path

    def save_torrent_file(self, torrent_file, path):
        if os.path.exists(torrent_file):
            shutil.copy(torrent_file, path)
        else:
            r = self.session_get(torrent_file)
            with open(path, 'wb') as fp:
                fp.write(r.content)

    def parse_url_for_value(self, url, key):
        o = urlparse(url)
        query = parse_qs(o.query)
        return query.get(key, [None])[0]

    def get_chapter_id_for_url(self, url):
        return self.parse_url_for_value(url, "file")

    def can_stream_url(self, url):
        return self.settings.torrent_info_cmd and super().can_stream_url(url)

    def get_chapter_data_from_url(self, media_data, url):
        chapter_data = super().get_chapter_data_from_url(media_data, url)
        if chapter_data is None:
            chapter_num = self.parse_url_for_value(url, "number")
            if chapter_num is not None:
                chapter_id = media_data.get_chapter_number_to_id(int(chapter_num))
                chapter_data = media_data["chapters"].get(chapter_id, None)
            elif len(media_data["chapters"]) == 1:
                chapter_data = next(iter(media_data["chapters"].values()))
        return chapter_data

    def get_all_media_data_from_url(self, url):
        return self.search_for_media(None, url=url) if self.parts_server else super().get_all_media_data_from_url(url)

    @property
    def add_series_url_regex(self):
        return self.stream_url_regex


class Torrent(GenericTorrentServer):
    id = "torrent"
    stream_url_regex = re.compile(r".*torrent")

    def get_media_list(self, **kwargs):
        return []

    def search_for_media(self, term, **kwargs):
        return self.get_media_list(**kwargs)

    def get_media_data_from_url(self, url):
        torrent_file = url
        with tempfile.NamedTemporaryFile() as fp:
            if "?" in url and not os.path.exists(url) and os.path.exists(url.split("?", 2)[0]):
                torrent_file = url.split("?", 2)[0]
                self.save_torrent_file(torrent_file, fp.name)
            else:
                self.save_torrent_file(url, fp.name)
            for line in self.settings.run_cmd_and_save_output(self.settings.torrent_info_cmd, env_extra={"TORRENT_FILE": fp.name}).splitlines():
                key, value = line.split()
                key = re.sub(r"\W", "", key.lower())
                if key == "hash":
                    info_hash = value.replace("%", "")
                elif key == "name":
                    title = value

        return self.create_media_data(id=info_hash, name=title, torrent_files=[torrent_file])
