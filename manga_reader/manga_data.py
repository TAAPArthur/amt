

def create_chapter_data(id, title, number, read=False, date=None):
    return dict(id=id, title=title, number=number, read=read, data=date)


def create_page_data(url, id=None):
    return dict(url=url, id=id)


def create_manga_data(server_id, id, name):
    return dict(server_id=server_id, id=id, name=name, chapters=[])
