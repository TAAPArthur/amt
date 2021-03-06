from ..tracker import Tracker


class TestTracker(Tracker):
    id = "TestTracker"
    customList = []

    def __init__(self, session, settings=None):
        self.media_list = [
            [False, "Manga1", 0],
            [True, "Anime1", 0],
            [False, "MangaUnknown", 1],
            [False, "AnimeUnknown", 1],
            [False, "MangaInProgress", 1],
            [True, "AnimeInProgress", 1],
            [False, "MangaUnknown2", 1],
            [False, "AnimeUnknown2", 1],
        ]

    def update(self, list_of_updates):
        for id, progress in list_of_updates:
            self.media_list[id][2] = progress

    def get_tracker_list(self, user_name=None, id=None):

        return [self.get_media_dict(i, item[0], item[1], item[2]) for i, item in enumerate(self.media_list)] if not self.customList else self.customList

    def set_custom_anime_list(self, l):
        self.customList = [self.get_media_dict(i, True, item, 1) for i, item in enumerate(l)]
