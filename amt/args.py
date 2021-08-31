import argparse
import logging
import os

from .media_reader_cli import MediaReaderCLI
from .server import ANIME, MANGA, MEDIA_TYPES, NOVEL
from .settings import Settings
from .stats import Details, SortIndex, StatGroup


def gen_auto_complete(parser):
    """ Support autocomplete via argcomplete if installed"""
    try:  # pragma: no cover
        import argcomplete
        argcomplete.autocomplete(parser)
    except ImportError:
        pass


def get_set_setting(media_reader_settings, field_name, save_env=False, value=None, target=None, save_all=False):
    settings = Settings(home=media_reader_settings.home, skip_env_override=not save_env)
    if value:
        settings.set_field(field_name, value, server_or_media_id=target)
        settings.save(save_all=save_all)
    print("{} = {}".format(field_name, settings.get_field(field_name, target)))


def parse_args(args=None, media_reader=None, already_upgraded=False):
    SPECIAL_PARAM_NAMES = {"auto", "clear_cookies", "log_level", "no_save", "type", "func"}

    media_reader = media_reader if media_reader else MediaReaderCLI()
    parser = argparse.ArgumentParser()
    parser.add_argument("--auto", action="store_const", const=True, default=False, help="Automatically select input instead of prompting")
    parser.add_argument("--clear-cookies", default=False, action="store_const", const=True, help="Clear all cached cookies")
    parser.add_argument("--log-level", default="INFO", choices=logging._levelToName.values(), help="Controls verbosity of logs")
    parser.add_argument("--no-save", default=False, action="store_const", const=True, help="Do not save state/cookies")

    sub_parsers = parser.add_subparsers(dest="type")

    # cookie
    cookie_parser = sub_parsers.add_parser("add-cookie", description="Add cookie")
    cookie_parser.add_argument("--path", default="/")
    cookie_parser.add_argument("id", choices=[server.id for server in media_reader.get_servers() if server.domain])
    cookie_parser.add_argument("name")
    cookie_parser.add_argument("value")

    # add remove
    search_parsers = sub_parsers.add_parser("search", description="Search for and add media")
    search_parsers.add_argument("--media-type", choices=MEDIA_TYPES.keys(), help="Filter for a specific type")
    search_parsers.add_argument("--server", choices=media_reader.get_servers_ids(), dest="server_id")
    search_parsers.add_argument("--exact", action="store_const", const=True, default=False, help="Only show exact matches")
    search_parsers.add_argument("term", help="The string to search by")
    search_parsers.set_defaults(func=media_reader.search_add)

    select_chapter_parsers = sub_parsers.add_parser("select", description="Search for and add media")
    select_chapter_parsers.add_argument("--media-type", choices=MEDIA_TYPES.keys(), help="Filter for a specific type")

    select_chapter_parsers.add_argument("--server", choices=media_reader.get_servers_ids(), dest="server_id")
    select_chapter_parsers.add_argument("--exact", action="store_const", const=True, default=False, help="Only show exact matches")
    select_chapter_parsers.add_argument("--quality", "-q", default=0, type=int)
    select_chapter_parsers.add_argument("term", help="The string to search by")
    select_chapter_parsers.set_defaults(func=media_reader.select_chapter)

    migrate_parsers = sub_parsers.add_parser("migrate", description="Move media to another server")
    migrate_parsers.add_argument("--self", action="store_const", const=True, default=False, help="Re-adds the media", dest="move_self")
    migrate_parsers.add_argument("name", choices=media_reader.get_all_names(), help="Global id of media to move")

    add_parsers = sub_parsers.add_parser("add-from-url", description="Add media by human viewable location")
    add_parsers.add_argument("url", help="Either the series home page or the page for an arbitrary chapter (depends on server)")

    remove_parsers = sub_parsers.add_parser("remove", description="Remove media")
    remove_parsers.add_argument("id", choices=media_reader.get_all_single_names(), help="Global id of media to remove")
    remove_parsers.set_defaults(func=media_reader.remove_media)

    # update and download
    update_parser = sub_parsers.add_parser("update", description="Update all media")
    update_parser.add_argument("--download", "-d", action="store_const", const=True, default=False, help="Update and download")
    update_parser.add_argument("--replace", "-r", action="store_const", const=True, default=False, help="Replace existing metadata instead of media_readerending")
    update_parser.add_argument("--media-type", choices=MEDIA_TYPES.keys(), help="Filter for a specific type")
    update_parser.add_argument("name", choices=media_reader.get_all_names(), default=None, nargs="?", help="Update only specified media")

    download_parser = sub_parsers.add_parser("download-unread", help="Downloads all chapters that have not been read")
    download_parser.add_argument("--media-type", choices=MEDIA_TYPES.keys(), help="Filter for a specific type")
    download_parser.add_argument("--limit", type=int, default=0, help="How many chapters will be downloaded per series")
    download_parser.add_argument("name", choices=media_reader.get_all_names(), default=None, nargs="?", help="Download only series determined by name")
    download_parser.set_defaults(func=media_reader.download_unread_chapters)

    download_specific_parser = sub_parsers.add_parser("download", help="Used to download specific chapters")
    download_specific_parser.add_argument("name", choices=media_reader.get_all_single_names())
    download_specific_parser.add_argument("start", type=float, default=0, help="Starting chapter (inclusive)")
    download_specific_parser.add_argument("end", type=float, nargs="?", default=0, help="Ending chapter (inclusive)")
    download_specific_parser.set_defaults(func=media_reader.download_specific_chapters)

    # media consumption

    bundle_parser = sub_parsers.add_parser("bundle", help="Bundle individual manga pages into a single file")
    bundle_parser.add_argument("-s", "--shuffle", default=False, action="store_const", const=True)
    bundle_parser.add_argument("-l", "--limit", default=0, type=int)
    bundle_parser.add_argument("-i", "--ignore-errors", default=False, action="store_const", const=True)
    bundle_parser.add_argument("name", choices=media_reader.get_all_names(MANGA), default=None, nargs="?")
    bundle_parser.set_defaults(func=media_reader.bundle_unread_chapters)

    read_parser = sub_parsers.add_parser("read", help="Open a saved bundle for reading. If the command exits with status 0, then the container chapters will be marked read")
    read_parser.add_argument("name", default=None, nargs="?", choices=os.listdir(media_reader.settings.bundle_dir), help="Name of the bundle")
    read_parser.set_defaults(func=media_reader.read_bundle)

    view_parser = sub_parsers.add_parser("view", help="View pages of chapters")
    view_parser.add_argument("--abs", default=False, action="store_const", const=True, dest="force_abs")
    view_parser.add_argument("--any-unread", "-a", default=False, action="store_const", const=True)
    view_parser.add_argument("--limit", "-l", default=0, type=int)
    view_parser.add_argument("--shuffle", "-s", default=False, action="store_const", const=True)
    view_parser.add_argument("name", choices=media_reader.get_all_names(MANGA | NOVEL), default=None, nargs="?")
    view_parser.add_argument("num_list", default=None, nargs="*", type=float)
    view_parser.set_defaults(func=media_reader.play)

    play_parser = sub_parsers.add_parser("play", help="Streams anime; this won't download any files; if the media is already downloaded, it will be used directly")
    play_parser.add_argument("--abs", default=False, action="store_const", const=True, dest="force_abs")
    play_parser.add_argument("--any-unread", "-a", default=False, action="store_const", const=True)
    play_parser.add_argument("--limit", "-l", default=0, type=int)
    play_parser.add_argument("--quality", "-q", default=0, type=int)
    play_parser.add_argument("--shuffle", "-s", default=False, action="store_const", const=True)
    play_parser.add_argument("name", choices=media_reader.get_all_names(ANIME), default=None, nargs="?")
    play_parser.add_argument("num_list", default=None, nargs="*", type=float)

    steam_parser = sub_parsers.add_parser("stream", help="Streams anime; this won't download any files; if the media is already downloaded, it will be used directly")
    steam_parser.add_argument("--cont", default=False, action="store_const", const=True)
    steam_parser.add_argument("--download", default=False, action="store_const", const=True)
    steam_parser.add_argument("--quality", "-q", default=0, type=int)
    steam_parser.add_argument("url")

    stream_url_parser = sub_parsers.add_parser("get-stream-url", help="Gets the steaming url for the media")
    stream_url_parser.add_argument("-s", "--shuffle", default=False, action="store_const", const=True)
    stream_url_parser.add_argument("name", choices=media_reader.get_all_names(ANIME), default=None, nargs="?")

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
    import_parser.add_argument("--media-type", default="ANIME", choices=MEDIA_TYPES.keys(), help="Filter for a specific type")
    import_parser.add_argument("--name", default=None, nargs="?", help="Name Media")
    import_parser.add_argument("files", nargs="+")
    import_parser.set_defaults(func=media_reader.import_media)

    # info
    list_parser = sub_parsers.add_parser("list")
    list_parser.add_argument("--only-out-of-date", default=False, action="store_const", const=True)
    chapter_parsers = sub_parsers.add_parser("list-chapters")
    chapter_parsers.add_argument("name", choices=media_reader.get_all_names())
    sub_parsers.add_parser("list-servers")

    # credentials
    login_parser = sub_parsers.add_parser("login", description="Relogin to all servers")
    login_parser.add_argument("--force", action="store_const", const=True, default=False, help="Force re-login")
    login_parser.add_argument("--servers", default=None, choices=media_reader.get_servers_ids_with_logins(), nargs="*", dest="server_ids")
    login_parser.set_defaults(func=media_reader.test_login)

    # stats
    stats_parser = sub_parsers.add_parser("stats", description="Show tracker stats")
    stats_parser.add_argument("--media-type", choices=MEDIA_TYPES.keys(), help="Filter for a specific type")
    stats_parser.add_argument("--refresh", action="store_const", const=True, default=False, help="Don't use cached data")
    stats_parser.add_argument("--details", action="store_const", const=True, default=False, help="Show media")
    stats_parser.add_argument("--details-type", "-d", choices=list(map(lambda x: x, Details)), type=lambda x: Details[x], default=Details.NAME, help="How details are displayed")
    stats_parser.add_argument("--stat-group", "-g", choices=list(map(lambda x: x, StatGroup)), type=lambda x: StatGroup[x], default=StatGroup.NAME, help="Choose stat grouping")
    stats_parser.add_argument("--sort-index", "-s", choices=list(map(lambda x: x, SortIndex)), type=lambda x: SortIndex[x], default=SortIndex.SCORE.name, help="Choose sort index")
    stats_parser.add_argument("--min-count", "-m", type=int, default=0, help="Ignore groups with fewer than N elements")
    stats_parser.add_argument("--min-score", type=float, default=1, help="Ignore entries with score less than N")
    stats_parser.add_argument("--user-id", default=None, nargs="?", help="id to load tracking info of")
    stats_parser.add_argument("username", default=None, nargs="?", help="Username to load info of; defaults to the currently authenticated user")

    # trackers and progress
    sub_parsers.add_parser("auth")

    load_parser = sub_parsers.add_parser("load", description="Attempts to add all tracked media")
    load_parser.add_argument("--force", action="store_const", const=True, default=False, help="Force set of read chapters to be in sync with progress")
    load_parser.add_argument("--media-type", choices=MEDIA_TYPES.keys(), help="Filter for a specific type")
    load_parser.add_argument("--local-only", action="store_const", const=True, default=False, help="Only attempt to find a match among local media")
    load_parser.add_argument("--progress-only", "-p", action="store_const", const=True, default=False, help="Only update progress of tracked media", dest="update_progress_only")
    load_parser.add_argument("--user-id", default=None, nargs="?", help="id to load tracking info of")
    load_parser.add_argument("user_name", default=None, nargs="?", help="Username to load tracking info of; defaults to the currently authenticated user")
    load_parser.set_defaults(func=media_reader.load_from_tracker)

    untrack_paraser = sub_parsers.add_parser("untrack", description="Removing tracker info")
    untrack_paraser.add_argument("--media-type", choices=MEDIA_TYPES.keys(), help="Filter for a specific type")
    untrack_paraser.add_argument("name", choices=media_reader.get_all_single_names(), nargs="?", help="Media to untrack")
    untrack_paraser.set_defaults(func=media_reader.remove_tracker)

    copy_tracker_parser = sub_parsers.add_parser("copy-tracker", description="Copies tracking info from src to dest")
    copy_tracker_parser.add_argument("src", choices=media_reader.get_all_single_names(), help="Src media")
    copy_tracker_parser.add_argument("dst", choices=media_reader.get_all_single_names(), help="Dst media")

    sync_parser = sub_parsers.add_parser("sync", description="Attempts to update tracker with current progress")
    sync_parser.add_argument("--force", action="store_const", const=True, default=False, help="Allow progress to decrease")
    sync_parser.add_argument("--dry-run", action="store_const", const=True, default=False, help="Don't actually update trackers")
    sync_parser.add_argument("--media-type", choices=MEDIA_TYPES.keys(), help="Filter for a specific type")
    sync_parser.set_defaults(func=media_reader.sync_progress)

    mark_unread_parsers = sub_parsers.add_parser("mark-unread", description="Mark all known chapters as unread")
    mark_unread_parsers.add_argument("--media-type", choices=MEDIA_TYPES.keys(), help="Filter for a specific type")
    mark_unread_parsers.add_argument("name", default=None, choices=media_reader.get_all_names(), nargs="?")
    mark_unread_parsers.set_defaults(func=media_reader.mark_read)
    mark_unread_parsers.set_defaults(force=True, N=-1, abs=True)

    mark_parsers = sub_parsers.add_parser("mark-read", description="Mark all known chapters as read")
    mark_parsers.add_argument("--abs", action="store_const", const=True, default=False, help="Treat N as an abs number")
    mark_parsers.add_argument("--force", "-f", action="store_const", const=True, default=False, help="Allow chapters to be marked as unread")
    mark_parsers.add_argument("--media-type", choices=MEDIA_TYPES.keys(), help="Filter for a specific type")
    mark_parsers.add_argument("name", default=None, choices=media_reader.get_all_names(), nargs="?")
    mark_parsers.add_argument("N", type=int, default=0, nargs="?", help="Consider the last N chapters as not up-to-date")

    offset_parser = sub_parsers.add_parser("offset")
    offset_parser.add_argument("name", default=None, choices=media_reader.get_all_names())
    offset_parser.add_argument("offset", type=int, default=0, nargs="?", help="Decrease the chapter number reported by the server by N")

    # settings
    settings_parsers = sub_parsers.add_parser("setting")
    settings_parsers.add_argument("--target", default=None, choices=media_reader.get_all_names(), nargs="?", help="Get/set for specific settings")
    settings_parsers.add_argument("field_name", choices=Settings.get_members())
    settings_parsers.add_argument("value", default=None, nargs="?")
    settings_parsers.add_argument("--save-env", action="store_const", const=True, default=False)
    settings_parsers.add_argument("--save-all", action="store_const", const=True, default=False)
    settings_parsers.set_defaults(func=get_set_setting, media_reader_settings=media_reader.settings)

    get_file_parsers = sub_parsers.add_parser("get-file")
    get_file_parsers.add_argument("file", default=None, choices=["settings_file", "metadata", "cookie_file"])
    get_file_parsers.set_defaults(func=lambda file: print(getattr(media_reader.settings, f"get_{namespace.file}")()))

    # upgrade state
    upgrade_parser = sub_parsers.add_parser("upgrade", description="Upgrade old state to newer format")
    upgrade_parser.add_argument("--force", "-f", action="store_const", const=True, default=False, help="Allow chapters to be marked as unread")
    upgrade_parser.set_defaults(func=media_reader.upgrade_state)

    # store password state
    password_parser = sub_parsers.add_parser("set-password", description="Set password")
    password_parser.add_argument("server_id", choices=media_reader.get_servers_ids_with_logins())
    password_parser.add_argument("username")
    password_parser.set_defaults(func=media_reader.settings.store_credentials)

    gen_auto_complete(parser)

    namespace = parser.parse_args(args)
    logging.getLogger().setLevel(namespace.log_level)

    if namespace.clear_cookies:
        media_reader.session.cookies.clear()

    media_reader.auto_select = namespace.auto
    action = namespace.type
    kwargs = {k: v for k, v in vars(namespace).items() if k not in SPECIAL_PARAM_NAMES}
    if "media_type" in namespace:
        kwargs["media_type"] = MEDIA_TYPES.get(namespace.media_type, None)
    func = namespace.func if "func" in namespace else getattr(media_reader, action.replace("-", "_"))
    func(**kwargs)

    if not namespace.no_save and ("dry_run" not in namespace or not namespace.dry_run):
        media_reader.state.save()
