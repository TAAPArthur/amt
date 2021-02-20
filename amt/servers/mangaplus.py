import re
from dataclasses import dataclass
from enum import IntEnum
from typing import List

import unidecode
from pure_protobuf.dataclasses_ import field, loads, message
from pure_protobuf.types import int32

from ..server import Server

LANGUAGES_CODES = dict(
    en=0,
    es=1,
)
RE_ENCRYPTION_KEY = re.compile(".{1,2}")


def load_response(data):
    resp_data = loads(MangaplusResponse, data)
    assert resp_data.success
    return resp_data


class Mangaplus(Server):
    id = "mangaplus"
    lang = "en"

    base_url = "https://mediaplus.shueisha.co.jp"
    api_url = "https://jumpg-webapi.tokyo-cdn.com/api"
    api_search_url = api_url + "/title_list/all"
    api_most_populars_url = api_url + "/title_list/ranking"
    api_media_url = api_url + "/title_detail?title_id={0}"
    api_chapter_url = api_url + "/manga_viewer?chapter_id={0}&split=yes&img_quality=high"
    media_url = base_url + "/titles/{0}"

    def get_media_list(self):
        r = self.session_get(self.api_most_populars_url)
        resp_data = load_response(r.content)

        results = []
        for title in resp_data.success.titles_ranking.titles:
            if title.language != LANGUAGES_CODES[self.lang]:
                continue
            results.append(self.create_media_data(id=title.id, name=title.name, cover=title.portrait_image_url))

        return results

    def search(self, term):
        r = self.session_get(self.api_search_url)

        resp_data = load_response(r.content)

        results = []
        term = unidecode.unidecode(term).lower()
        for title in resp_data.success.titles_all.titles:
            if title.language != LANGUAGES_CODES[self.lang]:
                continue
            if term not in unidecode.unidecode(title.name).lower():
                continue

            results.append(self.create_media_data(id=title.id, name=title.name, cover=title.portrait_image_url))

        return results

    def update_media_data(self, media_data):
        r = self.session_get(self.api_media_url.format(media_data["id"]))

        resp = load_response(r.content)

        resp_data = resp.success.title_detail

        for chapters in (resp_data.first_chapters, resp_data.last_chapters):
            for chapter in chapters:
                try:
                    number = int(chapter.name[1:] if chapter.name[0] == "#" else chapter.name)
                except ValueError:
                    number = 0
                self.update_chapter_data(media_data, id=chapter.id, title="{0} - {1}".format(chapter.name, chapter.subtitle), number=number, date=chapter.start_timestamp)

    def get_media_chapter_data(self, media_data, chapter_data):
        r = self.session_get(self.api_chapter_url.format(chapter_data["id"]))
        resp = load_response(r.content)

        resp_data = resp.success.media_viewer

        pages = []
        for page in resp_data.pages:
            if page.page is not None:
                pages.append(self.create_page_data(url=page.page.image_url, encryption_key=page.page.encryption_key))
        return pages

    def save_chapter_page(self, page_data, path):
        r = self.session_get(page_data["url"])

        if page_data["encryption_key"] is not None:
            # Decryption
            key_stream = [int(v, 16) for v in RE_ENCRYPTION_KEY.findall(page_data["encryption_key"])]
            block_size_in_bytes = len(key_stream)

            content = bytes([int(v) ^ key_stream[index % block_size_in_bytes] for index, v in enumerate(r.content)])
        else:
            content = r.content

        with open(path, "wb") as fp:
            fp.write(content)


# Protocol Buffers messages used to deserialize API responses
# https://gist.github.com/ZaneHannanAU/437531300c4df524bdb5fd8a13fbab50

class ActionEnum(IntEnum):
    DEFAULT = 0
    UNAUTHORIZED = 1
    MAINTAINENCE = 2
    GEOIP_BLOCKING = 3


class LanguageEnum(IntEnum):
    ENGLISH = 0
    SPANISH = 1


class UpdateTimingEnum(IntEnum):
    NOT_REGULARLY = 0
    MONDAY = 1
    TUESDAY = 2
    WEDNESDAY = 3
    THURSDAY = 4
    FRIDAY = 5
    SATURDAY = 6
    SUNDAY = 7
    DAY = 8


@message
@dataclass
class MangaPage:
    image_url: str = field(1)
    width: int32 = field(2)
    height: int32 = field(3)
    encryption_key: str = field(5, default=None)


@message
@dataclass
class Page:
    page: MangaPage = field(1, default=None)


@message
@dataclass
class MangaViewer:
    pages: List[Page] = field(1, default_factory=list)


@message
@dataclass
class Chapter:
    title_id: int32 = field(1)
    id: int32 = field(2)
    name: str = field(3)
    subtitle: str = field(4, default=None)
    start_timestamp: int32 = field(6, default=None)
    end_timestamp: int32 = field(7, default=None)


@message
@dataclass
class Title:
    id: int32 = field(1)
    name: str = field(2)
    author: str = field(3)
    portrait_image_url: str = field(4)
    landscape_image_url: str = field(5)
    view_count: int32 = field(6)
    language: LanguageEnum = field(7, default=LanguageEnum.ENGLISH)


@message
@dataclass
class TitleDetail:
    title: Title = field(1)
    title_image_url: str = field(2)
    synopsis: str = field(3)
    background_image_url: str = field(4)
    next_timestamp: int32 = field(5, default=0)
    update_timimg: UpdateTimingEnum = field(6, default=UpdateTimingEnum.DAY)
    viewing_period_description: str = field(7, default=None)
    first_chapters: List[Chapter] = field(9, default_factory=list)
    last_chapters: List[Chapter] = field(10, default_factory=list)
    is_simul_related: bool = field(14, default=True)
    chapters_descending: bool = field(17, default=True)


@message
@dataclass
class TitlesAll:
    titles: List[Title] = field(1)


@message
@dataclass
class TitlesRanking:
    titles: List[Title] = field(1)


@message
@dataclass
class SuccessResult:
    is_featured_updated: bool = field(1, default=False)
    titles_all: TitlesAll = field(5, default=None)
    titles_ranking: TitlesRanking = field(6, default=None)
    title_detail: TitleDetail = field(8, default=None)
    media_viewer: MangaViewer = field(10, default=None)


@message
@dataclass
class MangaplusResponse:
    success: SuccessResult = field(1, default=None)
