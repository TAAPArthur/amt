import json
import os
import requests


from ..server import Server
from ..util import name_parser
from ..util.media_type import MediaType
from requests.exceptions import RequestException


class RemoteServer(Server):
    id = None
    domain_list = None
    domain = None
    path = "/"
    auth = False
    username, password = None, None
    max_depth = 10
    protocol = "http://"
    implict_referer = False

    @classmethod
    def get_instances(clazz, session, settings=None):
        servers = []
        try:
            with open(settings.get_remote_servers_config_file(), "r") as f:
                for server_id, data in json.load(f).items():
                    server = clazz(session, settings)
                    server.id = server_id
                    for key, value in data.items():
                        if key == "media_type":
                            value = MediaType.get(value.upper())
                        setattr(server, key, value)
                    if server.path[0] != "/":
                        server.path = "/" + server.path
                    servers.append(server)
        except FileNotFoundError:
            pass
        return servers

    def get_base_url(self):
        if not self.domain:
            if self.has_login():
                self.get_credentials()
            with self._lock:
                saved_err = None
                if not self.domain:
                    for d in self.domain_list:
                        try:
                            self.session_get(d)
                            d = d.split("://", 2)[-1]
                            self.domain = d[:-1] if d[-1] == "/" else d
                            break
                        except RequestException as e:
                            saved_err = e
                    else:
                        raise saved_err
        return self.protocol + self.domain + self.path + ("/" if self.path[-1] != "/" else "")

    def has_login(self):
        return self.auth

    def login(self, username, password):
        self.session_get(self.get_base_url(), auth=(username, password))
        self.username, self.password = username, password
        self.is_premium = True

    def get_credentials(self):
        if self.username is None or self.password is None:
            credentials = super().get_credentials()
            if self.username is None:
                self.username = credentials[0]
            if self.password is None:
                self.password = credentials[-1]
        return (self.username, self.password)

    def session_get(self, url, **kwargs):
        if self.has_login() and "auth" not in kwargs:
            kwargs["auth"] = self.get_credentials()

        return super().session_get(url, **kwargs)

    def _create_media_data(self, link, media_name=None):
        if not media_name:
            link = requests.utils.unquote(link)
            media_name = os.path.splitext(os.path.basename(link if link[-1] != "/" else link[:-1]))[0]
        return self.create_media_data(name_parser.get_media_id_from_name(link), media_name, alt_id=link)

    def list_files(self, base_path="", path="", depth=None, is_hidden=False, in_media_dir=False):
        url = self.get_base_url() + base_path + path
        r = self.session_get(url)
        from bs4 import BeautifulSoup
        soup = self.soupify(BeautifulSoup, r)

        if not in_media_dir:
            for link in soup.findAll("a"):
                if link.getText() == self.settings.get_chapter_metadata_file_basename():
                    yield path
                    return

        for link in soup.findAll("a"):
            name = link.getText()
            if name == "." or name == ".." or (name.startswith(".") != is_hidden) or name.endswith(".json"):
                continue
            formatted_name = name + "/" if name[-1] != "/" and link.next_sibling == "/" else name
            child_path = os.path.join(path, formatted_name)
            if formatted_name[-1] != "/" or in_media_dir:
                yield child_path
            elif depth != 0 and formatted_name[-1] == "/":
                yield from self.list_files(base_path, path=child_path, depth=(depth or self.max_depth) - 1)

    def get_media_list(self, **kwargs):
        try:
            metadata_file_name = os.path.basename(self.settings.get_metadata_file())
            url = self.get_base_url()
            media_metadata = self.session_get_cache_json(os.path.join(url, metadata_file_name))
            for media_data in media_metadata["media"].values():
                alt_id = os.path.join("Media", media_data["server_id"], media_data["dir_name"]) + "/"
                yield self._create_media_data(alt_id, media_data["name"])
        except RequestException:
            yield from (self._create_media_data(link) for link in self.list_files())

    def update_media_data(self, media_data):
        if media_data["alt_id"][-1] != "/":
            self.update_chapter_data(media_data, media_data["alt_id"], title=media_data["name"], number=name_parser.get_number_from_file_name(media_data["alt_id"], media_name=media_data["name"], default_num=1))
            return

        try:
            chapter_metadata_url = os.path.join(self.get_base_url(), media_data["alt_id"], self.settings.get_chapter_metadata_file_basename())
            chapter_map = self.session_get(chapter_metadata_url).json()
            for chapter_data in chapter_map.values():

                abs_path = os.path.join(media_data["alt_id"], chapter_data["dir_name"])
                self.update_chapter_data(media_data, abs_path, title=chapter_data["title"], number=chapter_data["number"], premium=self.has_login(), special=chapter_data["special"])
            if chapter_map:
                return
        except RequestException:
            pass

        for link in self.list_files(media_data["alt_id"], depth=1, in_media_dir=True):
            self.update_chapter_data(media_data, os.path.join(media_data["alt_id"], link), title=link, number=name_parser.get_number_from_file_name(link, media_name=media_data["name"], default_num=1), premium=self.has_login())

    def get_media_chapter_data(self, media_data, chapter_data, stream_index=0):
        entires = self.list_files(chapter_data["id"]) if chapter_data["id"][-1] == "/" else [None]
        return [self.create_page_data(url=self.get_base_url() + chapter_data["id"] + ("/" + chapter_path if chapter_path else "")) for chapter_path in entires]

    def get_stream_urls(self, media_data, chapter_data):
        return [[x["url"] for x in self.get_media_chapter_data(media_data, chapter_data)]]

    def post_download(self, media_data, chapter_data, **kwargs):
        dir_path = self.settings.get_chapter_dir(media_data, chapter_data)
        if chapter_data["id"][-1] == "/":
            for p in self.list_files(chapter_data["id"], in_media_dir=True, is_hidden=True):
                for path in self.list_files(chapter_data["id"], path=p, is_hidden=False):
                    dest = os.path.join(dir_path, path)
                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                    r = self.session_get(os.path.join(self.get_base_url(), chapter_data["id"], path))
                    with open(dest, "wb") as fp:
                        fp.write(r.content)

    def can_stream_url(self, url):
        parts = url.split("://", 1)[-1].split("/", 1)
        if len(parts) != 2 or not parts[1].startswith(self.path[1:]):
            return False
        for d in self.domain_list:
            if d.endswith(parts[0]):
                return parts[1][len(self.path):]

    def get_media_data_from_url(self, url):
        relative_path = self.can_stream_url(url)
        for media_data in self.get_media_list():
            if relative_path.startswith(media_data["alt_id"]):
                return media_data

    def get_chapter_id_for_url(self, url):
        chapter_id = self.can_stream_url(url)
        parent_dir = os.path.dirname(chapter_id)
        possible_media_dir = os.path.dirname(parent_dir)
        chapter_metadata_url = os.path.join(self.get_base_url(), possible_media_dir, self.settings.get_chapter_metadata_file_basename())
        try:
            self.session_get(chapter_metadata_url)
            return parent_dir + "/"
        except RequestException:
            return chapter_id
