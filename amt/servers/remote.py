import os
import requests

from bs4 import BeautifulSoup

from ..server import Server
from ..util import name_parser
from ..util.media_type import MediaType


class RemoteServer(Server):
    id = None
    domain_list = None
    domain = None
    path = "/"
    auth = False
    username, password = None, None

    @classmethod
    def get_instances(clazz, session, settings=None):
        servers = []
        try:
            with open(settings.get_remote_servers_config_file(), "r") as f:
                for line in f:
                    if line.startswith("#") or not line.strip():
                        continue
                    key, value = line.strip().split("=", 2)
                    if key == "id":
                        servers.append(clazz(session, settings))
                    if key == "media_type":
                        value = MediaType.get(value.upper())
                        assert value, line
                    setattr(servers[-1], key, value)
        except (ImportError, FileNotFoundError):
            pass
        return servers

    def get_base_url(self):
        if not self.domain:
            if self.has_login():
                self.get_credentials()
            with self._lock:
                saved_err = None
                if not self.domain:
                    for d in self.domain_list.split(";"):
                        try:
                            self.session_get(d)
                            self.domain = d if d[-1] == "/" else d + "/"
                            break
                        except Exception as e:
                            saved_err = e
                    else:
                        raise saved_err
        return self.domain + self.path

    def has_login(self):
        return self.auth

    def login(self, username, password):
        self.session_get(self.get_base_url(), auth=(username, password))
        self.username, self.password = username, password
        self.is_premium = True

    def get_credentials(self):
        if self.username is None or self.password is None:
            u, p = super().get_credentials()
            if self.username is None:
                self.username = u
            if self.password is None:
                self.password = p
        return (self.username, self.password)

    def session_get(self, url, **kwargs):
        if self.has_login() and "auth" not in kwargs:
            kwargs["auth"] = self.get_credentials()

        return super().session_get(url, **kwargs)

    def list_files(self, base_path="", path="", depth=0, is_hidden=False):
        r = self.session_get(self.get_base_url() + base_path + path)
        soup = self.soupify(BeautifulSoup, r)

        for link in soup.findAll("a"):
            name = link.getText()
            if name == ".." or name.startswith(".") != is_hidden:
                continue
            formatted_name = name + "/" if name[-1] != "/" and link.next_sibling == "/" else name
            yield path, formatted_name
            if depth and formatted_name[-1] == "/":
                yield from self.list_files(base_path, path=path + formatted_name, depth=depth - 1)

    def _create_media_data(self, link):
        media_name = name_parser .get_media_name_from_file(requests.utils.unquote(link), is_dir=link[-1] == "/")
        return self.create_media_data(name_parser.get_media_id_from_name(link), media_name, alt_id=link)

    def get_media_list(self, **kwargs):
        return [self._create_media_data(link) for _, link in self.list_files()]

    def update_media_data(self, media_data):
        if media_data["alt_id"][-1] != "/":
            self.update_chapter_data(media_data, media_data["alt_id"], title=media_data["name"], number=name_parser .get_number_from_file_name(media_data["alt_id"], media_name=media_data["name"], default_num=1))
            return

        for _, link in self.list_files(media_data["alt_id"]):
            self.update_chapter_data(media_data, link, title=link, number=name_parser .get_number_from_file_name(link, media_name=media_data["name"], default_num=1), premium=self.has_login())

    def get_media_chapter_data(self, media_data, chapter_data, stream_index=0):
        if media_data["alt_id"][-1] != "/":
            return [self.create_page_data(url=self.get_base_url() + media_data["alt_id"])]
        chapter_url = media_data["alt_id"] + chapter_data["id"]
        entires = self.list_files(chapter_url) if chapter_data["id"][-1] == "/" else [(None, "")]
        return [self.create_page_data(url=self.get_base_url() + chapter_url + file_name) for _, file_name in entires]

    def get_stream_urls(self, media_data, chapter_data):
        return list(map(lambda x: x["url"], self.get_media_chapter_data(media_data, chapter_data)))

    def post_download(self, media_data, chapter_data, **kwargs):
        dir_path = self.settings.get_chapter_dir(media_data, chapter_data)
        chapter_url = media_data["alt_id"] + chapter_data["id"]
        if chapter_data["id"][-1] == "/":
            for _, f in self.list_files(chapter_url, is_hidden=True):
                for path, resource in self.list_files(chapter_url + f, is_hidden=False, depth=10):
                    if resource[-1] != "/":
                        os.makedirs(os.path.join(dir_path, f, path), exist_ok=True)
                        r = self.session_get(self.get_base_url() + chapter_url + f + path + resource)
                        with open(os.path.join(dir_path, f, path, resource), "wb") as fp:
                            fp.write(r.content)

    def can_stream_url(self, url):
        parts = url.split(self.path, 2)
        if len(parts) != 2:
            return False
        for d in self.domain_list.split(";"):
            if parts[0].endswith(d) or parts[0].endswith(d + "/"):
                return parts[1]

    def get_media_data_from_url(self, url):
        relative_path = self.can_stream_url(url)
        media_name = relative_path.split("/", 2)[0]
        return self._create_media_data(media_name + ("/" if "/" in relative_path else ""))

    def get_chapter_id_for_url(self, url):
        relative_path = self.can_stream_url(url)
        parts = relative_path.split("/", 3)
        return parts[0] if len(parts) == 1 else parts[1] + ("/" if len(parts) == 3 else "")
