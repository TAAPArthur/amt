# Anime Manga Tracker
CLI tool to download/stream anime/manga (and now light novels) from (mainly) official sources

The goal is to provide an simple and unobtrusive way to consume manga/anime using custom players.

The motivations stems from the fact that most UIs for reading/viewing manga/anime/light novels sucks or is unreliable at least on Linux. And while there may be some decent solutions on mobile and desktop, they generally only support type of media and force a GUI/password manager on the user.

## Dependencies
See [requirements.txt](requirements.txt) and [requirements-optional.txt](requirements-optional.txt).

The hard requirements are the python modules `requests`. If some of the optional other packages are not installed then some features may not be available or related servers may be disabled. See [below](#Supports) for the which servers depend on which dependency.

This program also relies on some external tools like `mpv` and `zathura` but other tools can be specified in settings. Similarly `tpm` is used by default but can also be replaced. If one doesn't feel like modifying the plain text settings file, global, server specific and media_type specific settings can be read from the environment. For example setting `AMT_VIEWER_ANIME="vlc {media}"` would cause vlc to be used instead of mpv to play anime. Also setting `AMT_PASSWORD_LOAD_CMD=""` in the env, will cause credentials to be prompted for when needed.

## Install
```
make install
```
which just invokes `python setup.py install "--root=$(DESTDIR)/"`

## Setup

### Password manager

Create/open `~/.config/amt/amt.conf` and set `password_save_cmd` and `password_load_cmd`. This commands will be used to save/load credentials. You control the format. For the save command, the strings `{username}` `{server_id}` will replaced with your username and the id of the server. The password will be available from stdin. `password_load_cmd` only has `{server_id}` and must output the username, newline and then the password.

If you don't want to set this up, you can set `password_manager_enabled` to False in the config file or set `AMT_PASSWORD_MANAGER_ENABLED=0` in your environment

### Quick setup

This assumes you have an Anilist account and want to add all media you are currently watching/reading. This assumes you have a password manager set

0. `amt auth` (optional) Get an auth token for your tracker and store it. This will let you load/sync progress to your tracker.
1. `amt load [username]` Will search for all media username is currently watching. If username is not provided the active user will be used. If there are multiple providers, you will be prompted to select which one. If you don't find the media you are looking for, press Enter and the search will be retried with a slightly different name
2. You can now watch/read your media with the `amt play [name]` or `amt view [name]` for anime or manga/novels respectively. Or `amt consume [name]` if you want both
3. `amt update` Check for new chapters/episodes. This is done automatically by default when new media is added
4. Whenever you feel like it, run `amt sync` to sync progress to the tracker. Note we only explicitly update the progress and don't set start/end data.

### Manual setup

#### If you have the name
1. `amt search term` Search for some media. The search mechanism are the same as for `amt load` described above
2. `amt play` to play from the first episode or `amt play N` to play the Nth episode. Subsequent `amt play` commands can be used to play the next media. Use `amt view` for manga/novels or consume if you don't care.

### If you have the url
* `amt add-from-url url` where url is the same the same one you would use to watch it from a browser. Then start from (2) above
* Or just `amt stream url` to not add the media internally. Add the `-c` option if you want to continue to the next episode


## Key commands
The general flow is to add a series to AMT, `update` if needed, then use `play`
to play the next episode of an anime or `bundle` and `read`  to download an
assimilate all unread chapters and then read them

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
* [HiDive](https://hidive.com/)
* [Vrv](https://vrv.co)

### Light novels
* [FreeWebNovel](https://freewebnovel.com) (unofficial)
* [J Novel club](https://j-novel.club/)

### Trackers
* [Anilist](https://anilist.co/home)

### Helpers
* [Nyaa](https://nyaa.si/) (unofficial)

### Media already owned
* Local Server -- media already downloaded on the machine; see the import subcommand
* Remove Server -- media hosted on some simple webserver (like darkhttpd)

Optional dependency breakdown
* PIL:                 required to download manga for Viz and JNovelClub
* beautifulsoup4:      required to download images for JNovelClub (only for light novel parts)
* beautifulsoup4:      required to enable DB multiverse, FreeWebNovel, Funimation, Nyaa, RemoteServer and Webtoons
* cloudscraper:        required to enable MangaSee and HumbleBundle
* cloudscraper:        potentially required to access all features of Crunchyroll (manga and anime)
* m3u8 & pycryptodome: required just download media for Crunchyroll and HiDive (enables more formats for Funimation and VRV)
* requests_oauthlib:   required to enable VRV
* beautifulsoup4 :     required to search entire selection for Crunchyroll (manga)

## Want to help
See [CONTRIBUTING](CONTRIBUTING.md).

Not everything is properly documented. See [settings.py](amt/settings.py) for a
list of all options and `amt --help` for all cli options. Feel free to open an
issue if something isn't clear.

## Why another downloader/tracker
There didn't seem to be adequate alternatives that had the following features

* Supports a wide portion of legal sites
* Supports anime, manga and light novels
* Integrates with a tracker
* Supports searching for manga/anime among many sites
* Can stream/download with just a series name and chapter/episode number instead of a raw url
* Supports external password managers, image and media players
* No GUI
* Plain text files and no database. Media is stored in structured directories. Settings file is plain text and media/chapter data is json and chapter metadata is split into a separate file per media. This makes it trivial to sync metadata or raw media files.
* Minimal dependencies
* Per media settings (ie can have different settings like reading direction for manga vs western comics)
* Supports premium accounts and purchased media (as opposed to those just available to subscribers)

## Similar Projects
* [youtube-dl](https://github.com/ytdl-org/youtube-dl)
* [manga-py](https://github.com/manga-py/manga-py)
* [Komikku](https://gitlab.com/valos/Komikku)

