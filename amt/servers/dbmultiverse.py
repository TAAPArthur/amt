from bs4 import BeautifulSoup
from ..server import Server


class Dbmultiverse(Server):
    id = 'dbmultiverse'
    name = 'Dragon Ball Multiverse'

    base_url = 'https://www.dragonball-multiverse.com'
    manga_url = base_url + '/en/chapters.html'
    chapter_url = base_url + '/en/chapters.html?chapter={}'
    page_url = base_url + '/en/page-{0}.html'
    cover_url = base_url + '/image.php?comic=page&num=0&lg=en&ext=jpg&small=1&pw=8f3722a594856af867d55c57f31ee103'

    synopsis = "Dragon Ball Multiverse (\"DBM\"), the sequel of the manga, is a dojinshi (manga created by non-professionals, using a universe and characters which are not theirs), made by Salagir and Gogeta Jr, from France."

    static_pages = True

    def get_manga_list(self):
        return [self.create_manga_data(id=1, name="Dragon Ball Multiverse (DBM)")]

    def update_manga_data(self, manga_data):

        r = self.session.get(self.manga_url)

        soup = BeautifulSoup(r.text, "lxml")

        chapters = soup.findAll("div", {"class": "cadrelect chapters"})
        chapters.sort(key=lambda x: int(x["ch"]))
        lastest_chapter = int(chapters[-1]["ch"])

        manga_data["info"] = dict(
            authors=['Gogeta Jr', 'Asura', 'Salagir'],
            genres=['Shounen'],
            status='ongoing',
            synopsis=self.synopsis,
            cover=self.cover_url,
        )

        for chapter in chapters:
            id = chapter["ch"]
            self.update_chapter_data(manga_data, id=id, number=int(id), title=chapter.find("h4").getText(), incomplete=id == lastest_chapter)

    def get_manga_chapter_data(self, manga_data, chapter_data):
        r = self.session.get(self.chapter_url.format(chapter_data["id"]))

        soup = BeautifulSoup(r.text, "lxml")
        page_info = soup.find("div", {"class": "pageslist"}).findAll("img")

        pages = []
        for page in page_info:
            r = self.session.get(self.page_url.format(page["title"]))
            soup = BeautifulSoup(r.text, "lxml")
            img = soup.find("img", {"id": "balloonsimg"})
            url = img["src"] if img else soup.find('div', id='balloonsimg').get('style').split(';')[0].split(':')[1][4:-1]
            pages.append(self.create_page_data(url=self.base_url + url))
        return pages

    def save_chapter_page(self, page_data, path):
        r = self.session.get(page_data["url"])

        with open(path, 'wb') as fp:
            fp.write(r.content)
