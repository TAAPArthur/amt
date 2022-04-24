
# Adding new servers

## Steps
1. Extend Server/TorrentHelper/Tracker which is defined in amt.server.py and implemented the needed methods. Servers are auto detected so nothing else needs to be done. The new server can be tested with the existing tests. If there is some interesting case that you feel is worth testing, feel free to add that under ServerSpecificTests.
2. Each server should go in its own file under amt/servers/ or amt/trackers unless if relates to another server. In the latter case it should go in the same file and common code should be refactored into a generic class. An enabled server should not inherit from another enabled Server.
3. Each Server should be specific to a single media_type. If a server supports multiple, there should be one for each class and possible an additional generic class to hold common methods.

There are 4 types of servers
1. Completely free servers (ie MangaPlus). These servers don't require a login and everything is available (region restrictions may apply). This is a special case of 2.
2. Subscription based servers with some free content (ie Crunchyroll). Some/most media can be accessed without logging in/having a premium account but not all.
3. Media library servers (ie parts of Viz, JNovelClub etc ). Media is purchased individually and only that set of media can be accessed. It may have free previews. If they don't have any non-free media, it should set `has_free_chapters` to false. This is used in tests to not fail if no media can be found. Note that is a given provider meets this criteria and either of the above, it should be split.
4. Customer servers. Self hosted servers or local media

There are also Trackers and TorrentHelpers, but there's only currently one of each and don't expect much deviation.


## Desired missing servers (in order)
* ~Crunchyroll Beta (Anime; type 2)~
* ~Funimation digital library (Anime; type 3)~
* ~HumbleBundle (type 3)~
* Webtoon (Manga; type 2) (well known api)
* ~HiDive (Anime; type 2)~
* Manga Planet (Anime; type 2)
* MyAnimeList (Tracker)

Other servers are welcome. All the code must run on Linux.
If there is a dedicated tool that has the desired functionality, it doesn't have to be re-implemented. The Server class could be a wrapper around it. However, I haven't yet seen tools that are both minimal and match the interface, so there have been a lot of rewrites from similar project.

## Can Provider X be added?
Maybe. If a similar project has it supported, it can probably be added. Most providers aren't forthcoming with their API so that will probably be the bottleneck.

Note that more unofficial or illegal servers won't be accepted.
Keep in mind that services like Amazon, Netflix, Google Play probably won't ever be added due to their DRM. If there is a way on Linux remove the DRM, please feel free to send a PR. It really hurts the availability of light novels, but that's their choice. [Cracking the drm](https://github.com/apprenticeharper/DeDRM_tools/wiki/Exactly-how-to-remove-DRM), at least for novels, can be done, but to be accepted here has to work completely on Linux and not require any recurring manual operation for the users.

## I want provider X but it doesn't meet the above criteria
Then it won't be accepted. You can drop the python file containing the server code in amt/servers (either system wide or just somewhere in your python path) and it'll work all the same.
