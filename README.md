#Anime Manga Tracker (beta)
Cli tool to download/stream anime/manga from (mainly) official sources

The goal is to provide an simple and unobtrusive way to consume manga/anime using custom players.


## Dependencies
See [requirements.txt](requirements.txt)

The hard requirements are the python modules `requests` and `beautifulsoup4`. If some other packages are installed, then some servers are disabled

This program also relies on some external tools like `mpv` and `zathura` but other tools can be specified in settings. Similarly `tpm` is used by default but can also be replaced.
## Install
```
make install
```
## Key commands
The general flow is to add a series to AMT, `update` if needed, then use `play` to play the next episode of an anime or `bundle` and `read`  to download an assimilate all unread chapters and then read them
* add-from-url -- adds a series based on the series home page (for when searching isn't available)
* bundle -- download all unread chapters and compile them into one file
* load -- load saved anime/manga from trackers
* play -- play an episode of an anime
* read -- read a previously created bundle
* search -- search for a title by name
* stream -- stream an anime by url (whatever url you'd use to watch in a browser)
* sync -- Sync progress back to trackers (doesn't change status)
* update -- check for new episodes and chapters

## Features
* Steam anime by url -- the same url you would use to watch in a browser
* Be notified on new chapters/episodes with a single command
* Download all unread episodes/chapters
* Bring your own anime/manga. The tool works with your personal collection

## Supports
### Manga
* [Viz](http://viz.com)
* [MangaPlus](https://mangaplus.shueisha.co.jp)
* [Crunchyroll](https://crunchyroll.com)
* [DB multiverse](https://www.dragonball-multiverse.com)
* mangasee (unofficial)
* mangadex (unofficial)

### Anime
* [Animelab](https://animelab.com/) (WIP)
* [Crunchyroll](https://crunchyroll.com)
* [Funimation](https://funimation.com)
* [Vrv](https://vrv.co)

### Light novels
* [J Novel club](https://j-novel.club/)

### Trackers
* [Anilist](https://anilist.co/home)

## Why another downloader/tracker
There didn't seem to be adequate alternatives that had the following features
* Supports a wide portion of legal sites
* Integrates with a tracker
* Supports searching for manga/anime among many sites
* Can stream/download with just a series name and chapter/episode number instead of a raw url
* Supports external password managers, image and media players
* No GUI

## TODO
* Server specific settings

## Caveats
* Images with vastly different resolution don't show up ideally in zathura. Bundling one server at a time and using a official sources mitigates the problem.
* Crunchyoll "seasons" don't aren't in sync with the actual seasons. For Non-consecutive cours may or may not be reported as 1 season. Long running series like One Piece and Gintama are broken into seasons arbitrary. This would only affect tracking and can be mitigatred with the "offset" command

## Similar Projects
* [youtube-dl](https://github.com/ytdl-org/youtube-dl)
* [manga-py](https://github.com/manga-py/manga-py)
* [Komikku](https://gitlab.com/valos/Komikku)

