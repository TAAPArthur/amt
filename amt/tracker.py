
class Tracker():
    id = None

    def __init__(self, session, settings=None):
        self.settings = settings
        self.session = session

    def get_media_dict(self, id, media_type, title, progress):
        return {"id": id, "media_type": media_type, "name": title, "progress": progress}

    def auth(self):
        pass

    def update(self, list_of_updates):
        pass

    def get_tracker_list(self, user_name=None, id=None):
        pass
