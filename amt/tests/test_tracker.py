from ..server import Tracker
from ..util.media_type import MediaType


class TestTracker(Tracker):
    id = "TestTracker"
    customList = []

    def __init__(self, session, settings=None):
        super().__init__(session, settings)
        self.media_list = []
        for media_type in list(MediaType):
            self.media_list.extend([
                [media_type, f"{media_type.name}1", 0, 0],
                [media_type, f"{media_type.name}Unknown", 1, 0],
                [media_type, f"{media_type.name}InProgress", 1, 9],
                [media_type, f"{media_type.name}2", 0, 9]
            ])

    def update(self, list_of_updates):
        for id, progress, _ in list_of_updates:
            self.media_list[id][2] = progress

    def get_tracker_list(self, user_name=None, id=None, status="CURRENT"):
        return [self.get_media_dict(id=i, media_type=item[0], name=item[1], progress=item[2], score=item[3]) for i, item in enumerate(self.media_list)] if not self.customList else self.customList

    def set_custom_anime_list(self, l, media_type=MediaType.ANIME):
        self.customList = [self.get_media_dict(i, media_type, item, 1) for i, item in enumerate(l)]
