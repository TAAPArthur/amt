# Maintainer: Arthur Williams <taaparthur at gmail dot com>
pkgname='amt'
pkgver='0.1.0'
pkgrel=0
pkgdesc='Anime and Manga cli tracker and download'
arch=('any')
license=('MIT')

depends=(python-requests python-beautifulsoup4 python-pure-protobuf python-pillow python-m3u8 python-pycryptodome)
optdepends=('python-argcomplete: autocomplete', 'zathura: pdf viewing', 'mpv: default anime player')
md5sums=('SKIP')
source=("git+https://github.com/TAAPArthur/amt.git")
package() {
  cd "amt"
  make DESTDIR=$pkgdir install
}
