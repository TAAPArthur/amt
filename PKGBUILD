# Maintainer: Arthur Williams <taaparthur at gmail dot com>
pkgname='amt'
pkgver='0.9.0'
pkgrel=0
pkgdesc='Anime and Manga cli tracker and download'
arch=('any')
license=('MIT')

depends=(python-requests python-beautifulsoup4)
optdepends=('python-argcomplete: autocomplete', 'zathura: default manga viewer', 'mpv: default anime player',
    'python-selenium: funimation -- to get around Incapsula protection',
    'python-m3u8: crunchyroll-anime',
    'crunchyroll-anime: crunchyroll-anime',
    'python-pillow: viz',
    'python-pure-protobuf: mangaplus',
    'python-unidecode:  mangaplus')
md5sums=('SKIP')
source=("git+https://github.com/TAAPArthur/amt.git")
package() {
  cd "amt"
  make DESTDIR=$pkgdir install
}
