

def ChapterData(id, title, date=None):
    return dict(title=title, id=id, data=date)


def PageData(url, id=None):
    return dict(url=url, id=id)


def create_manga_data(server_id, id, name):
    return dict(server_id=server_id, id=id, name=name, chapters=[])
