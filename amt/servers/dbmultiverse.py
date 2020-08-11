from bs4 import BeautifulSoup
from ..server import Server


class Dbmultiverse(Server):
    id = 'dbmultiverse'
    name = 'Dragon Ball Multiverse'

    base_url = 'https://www.dragonball-multiverse.com'
    media_url = base_url + '/en/chapters.html'
    chapter_url = base_url + '/en/chapters.html?chapter={}'
    page_url = base_url + '/en/page-{0}.html'
    cover_url = base_url + '/image.php?comic=page&num=0&lg=en&ext=jpg&small=1&pw=8f3722a594856af867d55c57f31ee103'

    synopsis = "Dragon Ball Multiverse (\"DBM\"), the sequel of the media, is a dojinshi (media created by non-professionals, using a universe and characters which are not theirs), made by Salagir and Gogeta Jr, from France."

    static_pages = True

    def get_media_list(self):
        return [self.create_media_data(id=1, name="Dragon Ball Multiverse (DBM)")]

    def update_media_data(self, media_data):

        r = self.session_get(self.media_url)

        soup = BeautifulSoup(r.text, "lxml")

        chapters = soup.findAll("div", {"class": "cadrelect chapters"})
        chapters.sort(key=lambda x: int(x["ch"]))
        lastest_chapter = int(chapters[-1]["ch"])

        media_data["info"] = dict(
            authors=['Gogeta Jr', 'Asura', 'Salagir'],
            genres=['Shounen'],
            status='ongoing',
            synopsis=self.synopsis,
            cover=self.cover_url,
        )

        for chapter in chapters:
            id = chapter["ch"]
            if id != lastest_chapter:
                self.update_chapter_data(media_data, id=id, number=int(id), title=chapter.find("h4").getText())

    def get_media_chapter_data(self, media_data, chapter_data):
        r = self.session_get(self.chapter_url.format(chapter_data["id"]))

        soup = BeautifulSoup(r.text, "lxml")
        page_info = soup.find("div", {"class": "pageslist"}).findAll("img")

        pages = []
        for page in page_info:
            r = self.session_get(self.page_url.format(page["title"]))
            soup = BeautifulSoup(r.text, "lxml")
            img = soup.find("img", {"id": "balloonsimg"})
            url = img["src"] if img else soup.find('div', id='balloonsimg').get('style').split(';')[0].split(':')[1][4:-1]
            pages.append(self.create_page_data(url=self.base_url + url))
        return pages

    def save_chapter_page(self, page_data, path):
        r = self.session_get(page_data["url"])

        with open(path, 'wb') as fp:
            fp.write(r.content)
