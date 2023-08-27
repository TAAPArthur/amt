import base64
import binascii
import hashlib
import re

from ..server import Server
from ..util.media_type import MediaType
from ..util.name_parser import get_media_name_from_volume_name, get_number_from_file_name

from Crypto.Cipher import AES
from Crypto.Util import Padding
from requests.exceptions import HTTPError


def decrypt_key(key, encoded_content_key):
    keyAes = AES.new(key, AES.MODE_ECB)
    content_key = base64.b64decode(encoded_content_key)
    return keyAes.decrypt(content_key)


class Kobo(Server):
    id = "kobo"
    media_type = MediaType.MANGA | MediaType.NOVEL
    has_free_chapters = False
    need_to_login_to_list = True

    domain = "kobo.com"

    device_auth_url = f"https://storeapi.{domain}/v1/auth/device"
    device_refresh_url = f"https://storeapi.{domain}/v1/auth/refresh"
    init_url = f"https://storeapi.{domain}/v1/initialization"

    stream_url_regex = re.compile(f"{domain}/ReadNow/([^/]*)")

    affiliate = "Kobo"
    application_version = "8.11.24971"
    default_platform_id = "00000000-0000-0000-0000-000000004000"
    display_profile = "Android"

    @property
    def device_id(self):
        cookie_name = "DeviceId"
        if not self.session_get_cookie(cookie_name):
            import uuid
            self.session_set_cookie(cookie_name, str(uuid.uuid4()))
        return self.session_get_cookie(cookie_name)

    @property
    def access_token(self):
        return self.session_get_cookie("AccessToken")

    @property
    def refresh_token(self):
        return self.session_get_cookie("RefreshToken")

    @property
    def user_key(self):
        return self.session_get_cookie("UserKey")

    @property
    def user_id(self):
        return self.session_get_cookie("UserId")

    def authenticate_device(self, refresh=False):
        def auth_headers():
            return {"Authorization": "Bearer " + self.access_token}
        if not self.access_token or refresh:
            import base64
            payload = {
                "AppVersion": self.application_version,
                "ClientKey": base64.b64encode(self.default_platform_id.encode()).decode(),
                "PlatformId": self.default_platform_id
            }
            headers = auth_headers() if self.access_token else {}
            if refresh:
                payload["RefreshToken"] = self.refresh_token
            else:
                payload["AffiliateName"] = self.affiliate
                payload["DeviceId"] = self.device_id
                if self.user_key:
                    payload["UserKey"] = self.user_key
            url = self.device_refresh_url if refresh else self.device_auth_url
            r = self.session_post(url, json=payload, headers=headers)
            data = r.json()

            if data["TokenType"] != "Bearer":
                raise Exception("Device authentication returned with an unsupported token type: '%s'" % data["TokenType"])

            self.session_set_cookies(data)
        return auth_headers()

    def session_get_auth(self, *args, **kwargs):
        try:
            headers = self.authenticate_device()
            return self.session_get_cache_json(*args, headers=headers, **kwargs)
        except HTTPError as e:
            if e.response.json()["ResponseStatus"]["ErrorCode"] == "ExpiredToken":
                headers = self.authenticate_device(refresh=True)
                return self.session_get_cache_json(*args, headers=headers, **kwargs)
            raise

    def get_url_maps(self):
        return self.session_get_auth(self.init_url, ttl=1)["Resources"]

    def list_books(self, media_data=None, chapter_id=None, **kwargs):
        data = self.session_get_auth(self.get_url_maps()["library_sync"], **kwargs)
        media_map = {}
        for item in data:
            if "NewEntitlement" in item:
                metadata = item["NewEntitlement"]["BookMetadata"]
                if chapter_id and chapter_id != metadata["RevisionId"]:
                    continue
                media_name, media_id = get_media_name_from_volume_name(metadata["Title"])
                if not media_data:
                    media_type = None
                    if "84a1c203-0341-41aa-898d-a745eb6e6b36" in metadata["Categories"]:
                        media_type = MediaType.MANGA
                    elif "Novel" in metadata["Title"]:
                        media_type = MediaType.NOVEL
                    media_map[media_id] = self.create_media_data(id=media_id, name=media_name, media_type=media_type)
                elif media_data["id"] == media_id:
                    self.update_chapter_data(media_data, id=metadata["RevisionId"], alt_id=metadata["Slug"], title=metadata["Title"], number=get_number_from_file_name(metadata["Title"], media_name=media_data["name"], default_num=1), data=metadata["PublicationDate"])
        return media_map.values()

    def get_media_list(self, **kwargs):
        yield from self.list_books()

    def update_media_data(self, media_data, **kwargs):
        self.list_books(media_data=media_data)

    def get_media_chapter_data(self, media_data, chapter_data, stream_index=0):
        data = self.session_get_auth(self.get_url_maps()["content_access_book"].replace("{ProductId}", chapter_data["id"]) + "?DisplayProfile=" + self.display_profile)
        drm_map = {"KDRM": 1, "None": 0}
        url = sorted(data["ContentUrls"], key=lambda x: drm_map.get(x["DRMType"], -1), reverse=True)[stream_index]["DownloadUrl"]

        base_key = hashlib.sha256((self.device_id + self.user_id).encode()).hexdigest()
        base_key = binascii.a2b_hex(base_key[32:])
        keys = {key["Name"]: decrypt_key(base_key, key["Value"]) for key in data["ContentKeys"]}

        return [self.create_page_data(url=url, encryption_key=keys)]

    def save_chapter_page(self, page_data, path):
        r = self.session_get(page_data["url"], headers=page_data["headers"])
        keys = page_data["encryption_key"]
        from io import BytesIO
        import zipfile
        with zipfile.ZipFile(BytesIO(r.content), "r") as inputZip, zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as outputZip:
            for filename in inputZip.namelist():
                zipped_file = inputZip.read(filename)
                content_key = keys.get(filename)
                if content_key is not None:
                    contentAes = AES.new(content_key, AES.MODE_ECB)
                    zipped_file = Padding.unpad(contentAes.decrypt(zipped_file), AES.block_size, "pkcs7")
                outputZip.writestr(filename, zipped_file)

    def get_chapter_id_for_url(self, url):
        return self.stream_url_regex.search(url).group(1)

    def get_media_data_from_url(self, url):
        return next(self.list_books(chapter_id=self.get_chapter_id_for_url(url)))
