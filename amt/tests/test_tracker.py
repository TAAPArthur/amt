from ..server import Tracker
from ..util.media_type import MediaType
from .test_server import TestServer, TestUnofficialServer


class TestTracker(Tracker):
    id = "TestTracker"
    customList = None

    def __init__(self, session, settings=None):
        super().__init__(session, settings)
        self.media_list = []
        for media_type in list(MediaType):
            self.media_list.extend([
                [media_type, f"{media_type.name}1", 0, 0, tuple(), tuple(), None],
                [media_type, f"{media_type.name}Unknown", 1, 0, tuple(), tuple(), 1],
                [media_type, f"{media_type.name}InProgress", 1, 9, tuple(), tuple(), 1e9],
                [media_type, f"{media_type.name}2", 1.5, 9, tuple(), tuple(), None]
            ])

        self.media_list.extend([
            [MediaType.MANGA, "None1", 0, 0, tuple(), tuple(), None],
            [MediaType.ANIME, "None2", 1.5, 9, tuple(), tuple(), None],
            [MediaType.NOVEL, "NoneInProgress", 1, 9, tuple(), tuple(), 1e9],
        ])

        self.media_list.append([MediaType.MANGA, "MediaWithSteamingLinks", 0, 0, tuple(), (TestServer.get_streamable_url(), TestUnofficialServer.get_streamable_url()), None])
        self.media_list.append([MediaType.MANGA, "MediaWithExternalLinks", 0, 0, [TestServer.get_addable_url(), TestUnofficialServer.get_addable_url()], tuple(), None])

    def get_auth_url(self):
        return "TrackerUrl.com"

    def update(self, list_of_updates):
        for id, progress, _ in list_of_updates:
            self.media_list[id][2] = progress

    def get_tracker_list(self, user_name=None, id=None, status="CURRENT"):
        return [self.get_media_dict(id=i, media_type=item[0], names={"English": item[1]}, progress=item[2], score=item[3], year=i, year_end=i, external_links=item[4], streaming_links=item[5], nextTimeStamp=item[6]) for i, item in enumerate(self.media_list)] if self.customList is None else self.customList

    def set_custom_anime_list(self, l, media_type=MediaType.ANIME):
        self.customList = [self.get_media_dict(i, media_type, {"English": item}, 1) for i, item in enumerate(l)]
