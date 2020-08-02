from ..server import Server


class Crunchyroll(Server):
    id = 'crunchyroll'
    lang = 'en'
    locale = 'enUS'
    has_login = True
    has_free_chapters = False

    base_url = 'https://www.crunchyroll.com'
    manga_url = base_url + '/comics/manga/{0}/volumes'

    start_session_url = 'https://api.crunchyroll.com/start_session.0.json'
    login_url = 'https://api.crunchyroll.com/login.0.json'

    api_base_url = 'https://api-manga.crunchyroll.com'
    api_auth_url = api_base_url + '/cr_authenticate?auth=&session_id={}&version=0&format=json'
    api_series_url = api_base_url + '/series?sort=popular'
    api_chapter_url = api_base_url + '/list_chapter?session_id={}&chapter_id={}&auth={}'
    api_chapters_url = api_base_url + '/chapters?series_id={}'

    api_auth_token = None
    api_session_id = None
    possible_page_url_keys = ['encrypted_mobile_image_url', 'encrypted_composed_image_url']
    page_url_key = possible_page_url_keys[0]

    _access_token = 'WveH9VkPLrXvuNm'
    _access_type = 'com.crunchyroll.crunchyroid'

    @staticmethod
    def decode_image(buffer):
        # Don't know why 66 is special
        return bytes(b ^ 66 for b in buffer)

    def _get_session_id(self):
        if 'session_id' in self.session.cookies:
            self.api_session_id = self.session.cookies['session_id']
            return

        data = self.session.post(
            self.start_session_url,
            data={
                'device_id': '1234567',
                'device_type': self._access_type,
                'access_token': self._access_token,
            }
        ).json()['data']
        self.api_session_id = data['session_id']

    def _store_login_data(self, data):
        self.api_auth_token = data['data']['auth']
        self.is_non_premium_account = not data['data']["user"]['premium']

    def needs_authentication(self):
        """
        Retrieves API session ID and authentication token
        """
        self._get_session_id()
        r = self.session.get(self.api_auth_url.format(self.api_session_id))
        data = r.json()

        if 'data' in data:
            self._store_login_data(data)
            return False

        return True

    def login(self, username, password):
        self._get_session_id()

        login = self.session.post(self.login_url,
                                  data={
                                      'session_id': self.api_session_id,
                                      'account': username,
                                      'password': password
                                  }).json()
        if 'data' in login:
            self._store_login_data(login)
            return True
        return False

    def get_manga_list(self):
        r = self.session.get(self.api_series_url)

        resp_data = r.json()
        resp_data.sort(key=lambda x: not x['featured'])

        result = []
        for item in resp_data:
            if 'locale' not in item:
                continue

            result.append(self.create_manga_data(id=item['series_id'], name=item['locale'][self.locale]['name']))

        return result

    def update_manga_data(self, manga_data: dict):
        r = self.session.get(self.api_chapters_url.format(manga_data['id']))

        json_data = r.json()
        resp_data = json_data['series']
        chapters = json_data['chapters']

        manga_data
        manga_data["info"] = dict(
            authors=[],
            scanlators=[],
            genres=[],
            status='ongoing',
            synopsis=resp_data['locale'][self.locale]['description'],
            cover=resp_data['locale'][self.locale]['thumb_url'],
            # url=self.manga_url.format(resp_data['url'][1:]),
        )

        # Chapters
        for chapter in chapters:
            date = None
            raw_date_str = chapter.get('availability_start', chapter.get("updated"))
            if raw_date_str:
                date = raw_date_str.split(' ')[0]

            self.update_chapter_data(manga_data, id=chapter['chapter_id'], number=chapter['number'], title=chapter['locale'][self.locale]['name'], premium=True, date=date)

    def get_manga_chapter_data(self, manga_data, chapter_data):
        r = self.session.get(self.api_chapter_url.format(self.api_session_id, chapter_data["id"], self.api_auth_token))
        raw_pages = r.json()['pages']
        raw_pages.sort(key=lambda x: int(x['number']))
        pages = [self.create_page_data(url=page['locale'][self.locale][self.page_url_key]) for page in raw_pages if page["locale"]]

        return pages

    def save_chapter_page(self, page_data, path):
        r = self.session.get(page_data["url"])
        buffer = self.decode_image(r.content)
        with open(path, 'wb') as fp:
            fp.write(buffer)
