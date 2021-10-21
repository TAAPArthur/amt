# Anime Manga Tracker (beta)
CLI tool to download/stream anime/manga (and now light novels) from (mainly) official sources

The goal is to provide an simple and unobtrusive way to consume manga/anime using custom players.

The motivations stems from the fact that most UIs for reading/viewing manga/anime/light novels sucks or is unreliable at least on Linux. And while there may be some decent solutions on mobile and desktop, they generally only support type of media and force a GUI/password manager on the user.

## Dependencies
See [requirements.txt](requirements.txt) and [requirements-optional.txt](requirements-optional.txt).

The hard requirements are the python modules `requests`. If some of the optional other packages are not installed then some features may not be available or related servers may be disabled. See [below](#Supports) for the which servers depend on which dependency.

This program also relies on some external tools like `mpv` and `zathura` but other tools can be specified in settings. Similarly `tpm` is used by default but can also be replaced. If one doesn't feel like modifying the plain text settings file, global, server specific and media_type specific settings can be read from the environment. For example setting `AMT_VIEWER_ANIME=vlc {media}` would cause vlc to be used instead of mpv to play anime. Also setting `AMT_PASSWORD_LOAD_CMD=""` in the env, will cause credentials to be asked for when needed.

## Install
```
make install
```

## Key commands
The general flow is to add a series to AMT, `update` if needed, then use `play` to play the next episode of an anime or `bundle` and `read`  to download an assimilate all unread chapters and then read them

* add-from-url -- adds a series based on the series home page (for when searching isn't available)
* bundle -- download all unread manga chapters and compile them into one file
* list -- list all added media
* load -- load saved anime/manga from trackers
* play/view -- play the next episode of an anime or view the next chapter of manga/light novel
* read -- read a previously created bundle
* search -- search for a title by name
* stream -- stream an anime by url (whatever url you'd use to watch in a browser)
* sync -- Sync progress back to trackers (doesn't change status)
* update -- check for new episodes and chapters

## Features
* Steam anime by url -- the same url you would use to watch in a browser
* Add anime by url -- the same url you would use to watch in a browser
* Be notified on new chapters/episodes with a single command
* Download all unread episodes/chapters
* Bring your own anime/manga. The tool works with your personal collection
* Portable - should run anywhere python does

## Supports
### Manga
* [Crunchyroll](https://crunchyroll.com)
* [DB multiverse](https://www.dragonball-multiverse.com)
* [J Novel club](https://j-novel.club/)
* [MangaDex](https://mangadex.org/) (unofficial)
* [MangaPlus](https://mangaplus.shueisha.co.jp)
* [MangaSee](https://mangasee123.com/) (unofficial)
* [Viz Library](https://viz.com)
* [Viz](https://viz.com)

### Anime
* [Crunchyroll](https://crunchyroll.com)
* [Funimation](https://funimation.com)
* [Vrv](https://vrv.co)

### Light novels
* [J Novel club](https://j-novel.club/)
* [WLNUpdates](https://www.wlnupdates.com/) (unofficial)

### Trackers
* [Anilist](https://anilist.co/home)

### Helpers
* [Nyaa](https://nyaa.si/) (unofficial)

### Media already owned
* Local Server -- media already downloaded on the machine; see the import subcommand
* Remove Server -- media hosted on some simple webserver (like darkhttpd)

Optional dependency breakdown
* PIL:                 required to download manga for Viz and JNovelClub
* PIL:                 required to use `force_page_parity` setting for image padding
* beautifulsoup4:      required to download images for JNovelClub (only for light novel parts)
* beautifulsoup4:      required to enable DB multiverse, Funimation, WLNUpdates, Nyaa and RemoteServer
* beautifulsoup4:      required for `quick_test_coverage` make target
* cloudscraper:        required to enable MangaSee
* m3u8 & pycryptodome: required just to stream media for Crunchyroll (enables more formats for Funimation and VRV)
* requests_oauthlib:   required to enable VRV

## Want to help
See [CONTRIBUTING.MD](CONTRIBUTING.MD)

## Why another downloader/tracker
There didn't seem to be adequate alternatives that had the following features

* Supports a wide portion of legal sites
* Supports anime, manga and light novels
* Integrates with a tracker
* Supports searching for manga/anime among many sites
* Can stream/download with just a series name and chapter/episode number instead of a raw url
* Supports external password managers, image and media players
* No GUI
* Plain text files and No database. Media is stored in structured directories. Settings file is plain text and media/chapter data is json and chapter metadata is split into a separate file per media. This makes it trivial to sync metadata or raw media files.
* Minimal dependencies

## Similar Projects
* [youtube-dl](https://github.com/ytdl-org/youtube-dl)
* [manga-py](https://github.com/manga-py/manga-py)
* [Komikku](https://gitlab.com/valos/Komikku)

