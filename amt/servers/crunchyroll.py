import logging

from ..server import Server


class Crunchyroll(Server):
    id = 'crunchyroll'
    lang = 'en'
    locale = 'enUS'
    has_login = True

    base_url = 'https://www.crunchyroll.com'
    manga_url = base_url + '/comics/manga/{0}/volumes'

    start_session_url = 'https://api.crunchyroll.com/start_session.0.json'
    login_url = 'https://api.crunchyroll.com/login.0.json'

    api_base_url = 'https://api-manga.crunchyroll.com'
    api_auth_url = api_base_url + '/cr_authenticate?session_id={}&version=0&format=json'
    api_series_url = api_base_url + '/series?sort=popular'
    api_chapter_url = api_base_url + '/list_chapter?session_id={}&chapter_id={}&auth={}'
    api_chapters_url = api_base_url + '/chapters?series_id={}'

    api_auth_token = None
    _api_session_id = None
    possible_page_url_keys = ['encrypted_mobile_image_url', 'encrypted_composed_image_url']
    page_url_key = possible_page_url_keys[0]

    _access_token = 'WveH9VkPLrXvuNm'
    _access_type = 'com.crunchyroll.crunchyroid'

    @staticmethod
    def decode_image(buffer):
        # Don't know why 66 is special
        return bytes(b ^ 66 for b in buffer)

    def get_session_id(self):
        if Crunchyroll._api_session_id:
            return Crunchyroll._api_session_id
        if 'session_id' in self.session.cookies:
            Crunchyroll._api_session_id = self.session.cookies['session_id']
            if not self.needs_authentication():
                return Crunchyroll._api_session_id
        data = self.session_post(
            self.start_session_url,
            data={
                'device_id': '1234567',
                'device_type': self._access_type,
                'access_token': self._access_token,
            }
        ).json()['data']
        Crunchyroll._api_session_id = data['session_id']
        return Crunchyroll._api_session_id

    def _store_login_data(self, data):
        self.api_auth_token = data['data']['auth']
        self.is_premium = data['data']["user"]['premium']

    def needs_authentication(self):
        r = self.session_get(self.api_auth_url.format(self.get_session_id()))
        data = r.json()
        if 'data' in data:
            self._store_login_data(data)
            return False
        if data.get("error", False):
            logging.info("Error authenticating %s", data)
        return True

    def login(self, username, password):
        login = self.session_post(self.login_url,
                                  data={
                                      'session_id': self.get_session_id(),
                                      'account': username,
                                      'password': password
                                  }).json()
        if 'data' in login:
            self._store_login_data(login)
            return True
        return False

    def get_media_list(self):
        r = self.session_get(self.api_series_url)

        resp_data = r.json()
        resp_data.sort(key=lambda x: not x['featured'])

        result = []
        for item in resp_data:
            if 'locale' not in item:
                continue

            result.append(self.create_media_data(id=item['series_id'], name=item['locale'][self.locale]['name']))

        return result

    def update_media_data(self, media_data: dict):
        r = self.session_get(self.api_chapters_url.format(media_data['id']))

        json_data = r.json()
        resp_data = json_data['series']
        chapters = json_data['chapters']

        # Chapters
        for chapter in chapters:
            date = None
            raw_date_str = chapter.get('availability_start', chapter.get("updated"))
            if raw_date_str:
                date = raw_date_str.split(' ')[0]

            self.update_chapter_data(media_data, id=chapter['chapter_id'], number=chapter['number'], title=chapter['locale'][self.locale]['name'], premium=True, date=date)

    def get_media_chapter_data(self, media_data, chapter_data):
        r = self.session_get(self.api_chapter_url.format(self.get_session_id(), chapter_data["id"], self.api_auth_token))
        raw_pages = r.json()['pages']
        raw_pages.sort(key=lambda x: int(x['number']))
        pages = [self.create_page_data(url=page['locale'][self.locale][self.page_url_key]) for page in raw_pages if page["locale"]]

        return pages

    def save_chapter_page(self, page_data, path):
        r = self.session_get(page_data["url"])
        buffer = self.decode_image(r.content)
        with open(path, 'wb') as fp:
            fp.write(buffer)
