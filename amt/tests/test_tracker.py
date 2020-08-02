from ..tracker import Tracker


class TestTracker(Tracker):
    id = "TestTracker"
    media_list = [
        [False, "Manga1", 0],
        [True, "Anime1", 0],
        [False, "MangaUnknown", 1],
        [False, "AnimeUnknown", 1],
        [False, "Manga2", 1],
        [True, "Anime2", 1],
        [False, "MangaUnknown2", 1],
        [False, "AnimeUnknown2", 1],
    ]

    def update(self, list_of_updates):
        for id, progress in list_of_updates:
            self.media_list[id][2] = progress

    def get_tracker_list(self, user_name=None, id=None):
        return [self.get_media_dict(i, item[0], item[1], item[2]) for i, item in enumerate(self.media_list)]
