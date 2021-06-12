import argparse
import logging
import os

from .app import Application
from .server import ANIME, MANGA, MEDIA_TYPES, NOVEL
from .settings import Settings


def gen_auto_complete(parser):
    """ Support autocomplete via argcomplete if installed"""
    try:
        import argcomplete
        argcomplete.autocomplete(parser)
    except ImportError:
        pass


def parse_args(args=None, app=None, already_upgraded=False):

    try:
        app = app if app else Application()
        parser = argparse.ArgumentParser()
        parser.add_argument("--auto", action="store_const", const=True, default=False, help="Automatically select input instead of prompting")
        parser.add_argument("--clear-cookies", default=False, action="store_const", const=True, help="Clear all cached cookies")
        parser.add_argument("--log-level", default="INFO", choices=logging._levelToName.values(), help="Controls verbosity of logs")
        parser.add_argument("--no-save", default=False, action="store_const", const=True, help="Do not save state/cookies")
        parser.add_argument("--no-verify", default=not Settings._verify, action="store_const", const=True, help="Skip SSL verification")
        parser.add_argument("--update", "-u", default=False, action="store_const", const=True, help="Check for new chapters and download them")

        sub_parsers = parser.add_subparsers(dest="type")

        # cookie
        cookie_parser = sub_parsers.add_parser("add-cookie", description="Add cookie")
        cookie_parser.add_argument("--path", default="/")
        cookie_parser.add_argument("id", choices=[server.id for server in app.get_servers() if server.domain])
        cookie_parser.add_argument("name")
        cookie_parser.add_argument("value")

        incap_cookie_parser = sub_parsers.add_parser("add-incapsula", description="Add incapsula cookie")
        incap_cookie_parser.add_argument("--path", default="/")
        incap_cookie_parser.add_argument("--name", default="incap_ses_979_998813")
        incap_cookie_parser.add_argument("id", choices=[server.id for server in app.get_servers() if server.domain])
        incap_cookie_parser.add_argument("value")

        sub_parsers.add_parser("js-cookie-parser", description="Open browser for all protected servers")

        # add remove
        search_parsers = sub_parsers.add_parser("search", description="Search for and add media")
        search_parsers.add_argument("--media-type", choices=MEDIA_TYPES.keys(), help="Filter for a specific type")
        search_parsers.add_argument("--server", choices=app.get_servers_ids())
        search_parsers.add_argument("--exact", action="store_const", const=True, default=False, help="Only show exact matches")
        search_parsers.add_argument("term", help="The string to search by")

        select_chapter_parsers = sub_parsers.add_parser("select", description="Search for and add media")
        select_chapter_parsers.add_argument("--media-type", choices=MEDIA_TYPES.keys(), help="Filter for a specific type")

        select_chapter_parsers.add_argument("--server", choices=app.get_servers_ids())
        select_chapter_parsers.add_argument("--exact", action="store_const", const=True, default=False, help="Only show exact matches")
        select_chapter_parsers.add_argument("--quality", "-q", default=0, type=int)
        select_chapter_parsers.add_argument("term", help="The string to search by")

        migrate_parsers = sub_parsers.add_parser("migrate", description="Move media to another server")
        migrate_parsers.add_argument("--self", action="store_const", const=True, default=False, help="Re-adds the media")
        migrate_parsers.add_argument("name", choices=app.get_all_names(), help="Global id of media to move")

        add_parsers = sub_parsers.add_parser("add-from-url", description="Add media by human viewable location")
        add_parsers.add_argument("url", help="Either the series home page or the page for an arbitrary chapter (depends on server)")

        remove_parsers = sub_parsers.add_parser("remove", description="Remove media")
        remove_parsers.add_argument("id", choices=app.get_all_single_names(), help="Global id of media to remove")

        # update and download
        update_parser = sub_parsers.add_parser("update", description="Update all media")
        update_parser.add_argument("--download", "-d", action="store_const", const=True, default=False, help="Update and download")
        update_parser.add_argument("--replace", "-r", action="store_const", const=True, default=False, help="Replace existing metadata instead of appending")
        update_parser.add_argument("--media-type", choices=MEDIA_TYPES.keys(), help="Filter for a specific type")
        update_parser.add_argument("name", choices=app.get_all_names(), default=None, nargs="?", help="Update only specified media")

        download_parser = sub_parsers.add_parser("download-unread", help="Downloads all chapters that have not been read")
        download_parser.add_argument("--media-type", choices=MEDIA_TYPES.keys(), help="Filter for a specific type")
        download_parser.add_argument("--limit", type=int, default=0, help="How many chapters will be downloaded per series")
        download_parser.add_argument("name", choices=app.get_all_names(), default=None, nargs="?", help="Download only series determined by name")

        download_specific_parser = sub_parsers.add_parser("download", help="Used to download specific chapters")
        download_specific_parser.add_argument("id", choices=app.get_all_single_names())
        download_specific_parser.add_argument("start", type=float, default=0, help="Starting chapter (inclusive)")
        download_specific_parser.add_argument("end", type=float, nargs="?", default=0, help="Ending chapter (inclusive)")

        # media consumption
        view_parser = sub_parsers.add_parser("view", help="View pages of chapters")
        view_parser.add_argument("-s", "--shuffle", default=False, action="store_const", const=True)
        view_parser.add_argument("-l", "--limit", default=0, type=int)
        view_parser.add_argument("-i", "--ignore-errors", default=False, action="store_const", const=True)
        view_parser.add_argument("--abs", default=False, action="store_const", const=True)
        view_parser.add_argument("name", choices=app.get_all_names(MANGA | NOVEL), default=None, nargs="?")
        view_parser.add_argument("num", default=None, nargs="*", type=float)

        bundle_parser = sub_parsers.add_parser("bundle", help="Bundle individual manga pages into a single file")
        bundle_parser.add_argument("-s", "--shuffle", default=False, action="store_const", const=True)
        bundle_parser.add_argument("-l", "--limit", default=0, type=int)
        bundle_parser.add_argument("-i", "--ignore-errors", default=False, action="store_const", const=True)
        bundle_parser.add_argument("name", choices=app.get_all_names(MANGA), default=None, nargs="?")

        read_parser = sub_parsers.add_parser("read", help="Open a saved bundle for reading. If the command exits with status 0, then the container chapters will be marked read")
        read_parser.add_argument("name", default=None, nargs="?", choices=os.listdir(app.settings.bundle_dir), help="Name of the bundle")

        steam_parser = sub_parsers.add_parser("stream", help="Streams anime; this won't download any files; if the media is already downloaded, it will be used directly")
        steam_parser.add_argument("--cont", default=False, action="store_const", const=True)
        steam_parser.add_argument("--download", default=False, action="store_const", const=True)
        steam_parser.add_argument("--quality", "-q", default=0, type=int)
        steam_parser.add_argument("url")

        play_parser = sub_parsers.add_parser("play", help="Streams anime; this won't download any files; if the media is already downloaded, it will be used directly")
        play_parser.add_argument("-s", "--shuffle", default=False, action="store_const", const=True)
        play_parser.add_argument("-c", "--cont", default=False, action="store_const", const=True, help="Keep playing until all streams have =been consumed or the player exits with non-zero status")
        play_parser.add_argument("--quality", "-q", default=0, type=int)
        play_parser.add_argument("--any-unread", "-a", default=False, action="store_const", const=True)
        play_parser.add_argument("--abs", default=False, action="store_const", const=True)
        play_parser.add_argument("name", choices=app.get_all_names(ANIME), default=None, nargs="?")
        play_parser.add_argument("num", default=None, nargs="*", type=float)

        stream_url_parser = sub_parsers.add_parser("get-stream-url", help="Gets the steaming url for the media")
        stream_url_parser.add_argument("-s", "--shuffle", default=False, action="store_const", const=True)
        stream_url_parser.add_argument("name", choices=app.get_all_names(ANIME), default=None, nargs="?")

        # clean
        clean_parser = sub_parsers.add_parser("clean", help="Removes unused media")
        clean_parser.add_argument("-b", "--bundles", default=False, action="store_const", const=True, help="Removes bundle info")
        clean_parser.add_argument("--remove-disabled-servers", default=False, action="store_const", const=True, help="Removes all servers not belonging to the active list")
        clean_parser.add_argument("--include-external", default=False, action="store_const", const=True, help="Doesn't skip local servers")
        clean_parser.add_argument("--remove-read", default=False, action="store_const", const=True, help="Removes all read chapters")
        clean_parser.add_argument("--remove-not-on-disk", default=False, action="store_const", const=True, help="Removes references where the backing directory is emtpy")

        # external
        import_parser = sub_parsers.add_parser("import")
        import_parser.add_argument("--link", action="store_const", const=True, default=False, help="Hard links instead of just moving the file")
        import_parser.add_argument("--media-type", choices=MEDIA_TYPES.keys(), help="Filter for a specific type")
        import_parser.add_argument("--name", default=None, nargs="?", help="Name Media")
        import_parser.add_argument("file", nargs="+")

        # info
        sub_parsers.add_parser("list")
        chapter_parsers = sub_parsers.add_parser("list-chapters")
        chapter_parsers.add_argument("name", choices=app.get_all_names())
        sub_parsers.add_parser("list-servers")

        # credentials
        login_parser = sub_parsers.add_parser("login", description="Relogin to all servers")
        login_parser.add_argument("--force", action="store_const", const=True, default=False, help="Force re-login")
        login_parser.add_argument("--servers", default=None, choices=app.get_servers_ids_with_logins(), nargs="*")

        # trackers and progress
        sub_parsers.add_parser("auth")

        load_parser = sub_parsers.add_parser("load", description="Attempts to add all tracked media")
        load_parser.add_argument("--force", action="store_const", const=True, default=False, help="Force set of read chapters to be in sync with progress")
        load_parser.add_argument("--media-type", choices=MEDIA_TYPES.keys(), help="Filter for a specific type")
        load_parser.add_argument("--local-only", action="store_const", const=True, default=False, help="Only attempt to find a match among local media")
        load_parser.add_argument("--progress-only", "-p", action="store_const", const=True, default=False, help="Only update progress of tracked media")
        load_parser.add_argument("name", default=None, nargs="?", help="Username to load tracking info of; defaults to the currently authenticated user")

        untrack_paraser = sub_parsers.add_parser("untrack", description="Removing tracker info")
        untrack_paraser.add_argument("--media-type", choices=MEDIA_TYPES.keys(), help="Filter for a specific type")
        untrack_paraser.add_argument("name", choices=app.get_all_single_names(), nargs="?", help="Media to untrack")

        copy_tracker_parser = sub_parsers.add_parser("copy-tracker", description="Copies tracking info from src to dest")
        copy_tracker_parser.add_argument("--media-type", choices=MEDIA_TYPES.keys(), help="Filter for a specific type")
        copy_tracker_parser.add_argument("src", choices=app.get_all_single_names(), help="Src media")
        copy_tracker_parser.add_argument("dst", choices=app.get_all_single_names(), help="Dst media")

        share_tracker_parser = sub_parsers.add_parser("share-tracker", description="Checks local media to see if tracking info can be shared")
        share_tracker_parser.add_argument("--media-type", choices=MEDIA_TYPES.keys(), help="Filter for a specific type")
        share_tracker_parser.add_argument("name", choices=app.get_all_single_names(), default=None, nargs="?")

        sync_parser = sub_parsers.add_parser("sync", description="Attempts to update tracker with current progress")
        sync_parser.add_argument("--force", action="store_const", const=True, default=False, help="Allow progress to decrease")
        sync_parser.add_argument("--dry-run", action="store_const", const=True, default=False, help="Don't actually update trackers")
        sync_parser.add_argument("--media-type", choices=MEDIA_TYPES.keys(), help="Filter for a specific type")

        mark_parsers = sub_parsers.add_parser("mark-up-to-date", description="Mark all known chapters as read")
        mark_parsers.add_argument("--abs", action="store_const", const=True, default=False, help="Treat N as an abs number")
        mark_parsers.add_argument("--force", action="store_const", const=True, default=False, help="Allow chapters to be marked as unread")
        mark_parsers.add_argument("--media-type", choices=MEDIA_TYPES.keys(), help="Filter for a specific type")
        mark_parsers.add_argument("name", default=None, choices=app.get_all_names(), nargs="?")
        mark_parsers.add_argument("N", type=int, default=0, nargs="?", help="Consider the last N chapters as not up-to-date")

        offset_parser = sub_parsers.add_parser("offset")
        offset_parser.add_argument("name", default=None, choices=app.get_all_names())
        offset_parser.add_argument("N", type=int, default=0, nargs="?", help="Decrease the chapter number reported by the server by N")

        # settings
        settings_parsers = sub_parsers.add_parser("setting")
        settings_parsers.add_argument("setting", choices=Settings.get_members())
        settings_parsers.add_argument("value", default=None, nargs="?")

        get_file_parsers = sub_parsers.add_parser("get-file")
        get_file_parsers.add_argument("file", default=None, choices=["settings_file", "metadata", "cookie_file"])

        # upgrade state
        sub_parsers.add_parser("upgrade", description="Upgrade old state to newer format")

        # store password state
        password_parser = sub_parsers.add_parser("set-password", description="Set password")
        password_parser.add_argument("server", default=None, choices=app.get_servers_ids_with_logins())
        password_parser.add_argument("username")
    except KeyError as e:
        logging.warn("Failed to parse arguments because of key error; attempting to upgrade state")
        if not app.settings.auto_upgrade_state:
            logging.error("Auto upgrade is not enabled; Please manually fix state: %s", app.settings.get_metadata())
        elif not already_upgraded:
            app.upgrade_state()
            parse_args(args=args, app=app, already_upgraded=True)
            return
        raise e

    gen_auto_complete(parser)

    namespace = parser.parse_args(args)
    logging.getLogger().setLevel(namespace.log_level)
    if namespace.update:
        app.update(download=True)

    app.settings._verify = not namespace.no_verify

    if namespace.clear_cookies:
        app.session.cookies.clear()

    action = namespace.type
    app.auto_select = namespace.auto
    if action == "add-cookie" or action == "add-incapsula":
        server = app.get_server(namespace.id)
        server.add_cookie(namespace.name, namespace.value, domain=app.get_server(namespace.id).domain, path=namespace.path)
    elif action == "add-from-url":
        app.add_from_url(namespace.url)
    elif action == "auth":
        tracker = app.get_primary_tracker()
        secret = tracker.auth()
        app.settings.store_secret(tracker.id, secret)
    elif action == "bundle":
        print(app.bundle_unread_chapters(name=namespace.name, shuffle=namespace.shuffle, limit=namespace.limit, ignore_errors=namespace.ignore_errors))
    elif action == "clean":
        app.clean(remove_disabled_servers=namespace.remove_disabled_servers, include_external=namespace.include_external, remove_read=namespace.remove_read, bundles=namespace.bundles, remove_not_on_disk=namespace.remove_not_on_disk)
    elif action == "copy-tracker":
        app.copy_tracker(namespace.src, namespace.dst)
    elif action == "download":
        app.download_specific_chapters(namespace.id, start=namespace.start, end=namespace.end)
    elif action == "download-unread":
        app.download_unread_chapters(namespace.name, media_type=MEDIA_TYPES.get(namespace.media_type, None), limit=namespace.limit)
    elif action == "list":
        app.list()
    elif action == "list-servers":
        app.list_servers()
    elif action == "list-chapters":
        app.list_chapters(namespace.name)
    elif action == "load":
        app.load_from_tracker(user_name=namespace.name, exact=False, media_type_filter=MEDIA_TYPES.get(namespace.media_type, None), local_only=namespace.local_only, update_progress_only=namespace.progress_only, force=namespace.force)
    elif action == "login":
        app.test_login(namespace.servers, force=namespace.force)
    elif action == "mark-up-to-date":
        app.mark_up_to_date(namespace.name, media_type=MEDIA_TYPES.get(namespace.media_type, None), N=namespace.N, force=namespace.force, abs=namespace.abs)
        app.list()
    elif action == "js-cookie-parser":
        app.maybe_fetch_extra_cookies()
    elif action == "offset":
        app.offset(namespace.name, offset=namespace.N)
    elif action == "get-stream-url":
        app.get_stream_url(name=namespace.name, shuffle=namespace.shuffle)
    elif action == "get-file":
        print(app.settings.get(f"get_{namespace.file}")())
    elif action == "play":
        print(app.play(name=namespace.name, cont=namespace.cont, shuffle=namespace.shuffle, num_list=namespace.num, quality=namespace.quality, any_unread=namespace.any_unread, force_abs=namespace.abs))
    elif action == "read":
        print(app.read_bundle(namespace.name))
    elif action == "migrate":
        app.migrate(name=namespace.name, move_self=namespace.self)
    elif action == "remove":
        app.remove_media(id=namespace.id)
    elif action == "import":
        app.import_media(namespace.file, media_type=MEDIA_TYPES.get(namespace.media_type, None) or ANIME, link=namespace.link, name=namespace.name)
    elif action == "search":
        if not app.search_add(namespace.term, server_id=namespace.server, media_type=MEDIA_TYPES.get(namespace.media_type, None), exact=namespace.exact):
            logging.warning("Could not find media %s", namespace.term)
    elif action == "select":
        app.select_chapter(namespace.term, quality=namespace.quality, server_id=namespace.server, media_type=MEDIA_TYPES.get(namespace.media_type, None), exact=namespace.exact)
    elif action == "setting":
        if namespace.value:
            app.settings.set(namespace.setting, namespace.value)
            app.settings.save()
        print("{} = {}".format(namespace.setting, app.settings.get(namespace.setting)))
    elif action == "stream":
        app.stream(namespace.url, cont=namespace.cont, download=namespace.download, quality=namespace.quality)
    elif action == "set-password":
        app.settings.store_credentials(namespace.server, namespace.username)
    elif action == "share-tracker":
        app.share_tracker(namespace.name, media_type=MEDIA_TYPES.get(namespace.media_type, None))
    elif action == "sync":
        app.sync_progress(force=namespace.force, media_type=MEDIA_TYPES.get(namespace.media_type, None), dry_run=namespace.dry_run)
    elif action == "untrack":
        app.remove_tracker(name=namespace.name, media_type=MEDIA_TYPES.get(namespace.media_type, None))
    elif action == "update":
        app.update(name=namespace.name, media_type=MEDIA_TYPES.get(namespace.media_type, None), download=namespace.download, replace=namespace.replace)
    elif action == "upgrade":
        app.upgrade_state()
    elif action == "view":
        print(app.view_chapters(name=namespace.name, shuffle=namespace.shuffle, limit=namespace.limit, ignore_errors=namespace.ignore_errors, num_list=namespace.num, force_abs=namespace.abs))

    if not namespace.no_save and ("dry_run" not in namespace or not namespace.dry_run):
        app.save()
