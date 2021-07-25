from ..server import ANIME, MEDIA_TYPES
from ..tracker import Tracker


class TestTracker(Tracker):
    id = "TestTracker"
    customList = []

    def __init__(self, session, settings=None):
        self.media_list = []
        for media_type_name in MEDIA_TYPES:
            self.media_list.extend([
                [MEDIA_TYPES[media_type_name], f"{media_type_name}1", 0, 0],
                [MEDIA_TYPES[media_type_name], f"{media_type_name}Unknown", 1, 0],
                [MEDIA_TYPES[media_type_name], f"{media_type_name}InProgress", 1, 9],
                [MEDIA_TYPES[media_type_name], f"{media_type_name}2", 0, 9]
            ])

    def update(self, list_of_updates):
        for id, progress, _ in list_of_updates:
            self.media_list[id][2] = progress

    def get_tracker_list(self, user_name=None, id=None, status="CURRENT"):
        return [self.get_media_dict(id=i, media_type=item[0], name=item[1], progress=item[2], score=item[3]) for i, item in enumerate(self.media_list)] if not self.customList else self.customList

    def set_custom_anime_list(self, l, media_type=ANIME):
        self.customList = [self.get_media_dict(i, media_type, item, 1) for i, item in enumerate(l)]
