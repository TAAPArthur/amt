import argparse
import logging

from .settings import Settings
from .state import State
from .stats import Details, SortIndex, StatGroup, TimeUnit
from .util.media_type import MediaType


def gen_auto_complete(parser):
    """ Support autocomplete via argcomplete if installed"""
    try:  # pragma: no cover
        import argcomplete
        argcomplete.autocomplete(parser, default_completer=None)
    except ImportError:
        pass


def add_file_completion(parser):
    try:  # pragma: no cover
        import argcomplete
        parser.completer = argcomplete.completers.FilesCompleter
    except ImportError:
        pass


def add_parser_helper(sub_parser, name, func_str=None, **kwargs):
    parser = sub_parser.add_parser(name, **kwargs)
    parser.set_defaults(func_str=func_str or name)
    return parser


def parse_args(args=None, media_reader=None, already_upgraded=False):
    SPECIAL_PARAM_NAMES = {"auto", "clear_cookies", "log_level", "no_save", "type", "func", "readonly", "func_str", "tmp_dir"}

    state = State(Settings()) if not media_reader else media_reader.state

    parser = argparse.ArgumentParser()
    parser.add_argument("--auto", action="store_const", const=True, default=False, help="Automatically select input instead of prompting")
    parser.add_argument("--clear-cookies", default=False, action="store_const", const=True, help="Clear all cached cookies")
    parser.add_argument("--log-level", default="INFO", choices=logging._levelToName.values(), help="Controls verbosity of logs")
    parser.add_argument("--no-save", default=False, action="store_const", const=True, help="Do not save state/cookies")
    parser.add_argument("--tmp-dir", default=False, action="store_const", const=True, help="Save state to tmp-dir")

    sub_parsers = parser.add_subparsers(dest="type")

    readonly_parsers = argparse.ArgumentParser(add_help=False)
    readonly_parsers.set_defaults(readonly=True)

    sub_search_parsers = argparse.ArgumentParser(add_help=False)
    sub_search_parsers.add_argument("--filter-by-preferred-lang", action="store_const", const=True, default=False, help="Sort results by preferred Settings:preferred_primary_language")
    sub_search_parsers.add_argument("--exact", action="store_const", const=True, default=False, help="Only show exact matches")
    sub_search_parsers.add_argument("--limit", type=int, default=10, help="How many chapters will be downloaded per series")
    sub_search_parsers.add_argument("--media-type", choices=list(MediaType), type=MediaType.__getattr__, help="Filter for a specific type")
    sub_search_parsers.add_argument("--server", choices=state.get_server_ids(), dest="server_id")

    # add remove
    search_parsers = add_parser_helper(sub_parsers, "search_for_media", aliases=["search"], parents=[sub_search_parsers], help="Search for and add media")
    search_parsers.add_argument("name", help="The string to search by")

    migrate_parsers = add_parser_helper(sub_parsers, "migrate", parents=[sub_search_parsers], help="Move media to another server")
    migrate_parsers.add_argument("--force-same-id", action="store_const", const=True, default=False, help="Forces the media id to be the same")
    migrate_parsers.add_argument("--self", action="store_const", const=True, default=False, help="Re-adds the media", dest="move_self")
    migrate_parsers.add_argument("name", choices=state.get_all_names(), help="Global id of media to move")

    add_parsers = add_parser_helper(sub_parsers, "add-from-url", help="Add media by human viewable location")
    add_parsers.add_argument("url", help="Either the series home page or the page for an arbitrary chapter (depends on server)")

    remove_parsers = add_parser_helper(sub_parsers, "remove", func_str="remove-media", help="Remove media")
    remove_parsers.add_argument("name", choices=state.get_all_single_names(), help="id of media to remove")

    # update and download
    update_parser = add_parser_helper(sub_parsers, "update", help="Update all media")
    update_parser.add_argument("--media-type", choices=list(MediaType), type=MediaType.__getattr__, help="Filter for a specific type")
    update_parser.add_argument("--no-shuffle", default=False, action="store_const", const=True)
    update_parser.add_argument("name", choices=state.get_all_names(), default=None, nargs="?", help="Update only specified media")

    download_parser = add_parser_helper(sub_parsers, "download-unread-chapters", aliases=["download-unread"], help="Downloads all chapters that have not been read")
    download_parser.add_argument("--force", "-f", default=False, action="store_const", const=True)
    download_parser.add_argument("--limit", "-l", type=int, default=0, help="How many chapters will be downloaded per series")
    download_parser.add_argument("--media-type", choices=list(MediaType), type=MediaType.__getattr__, help="Filter for a specific type")
    download_parser.add_argument("--stream-index", "-q", default=0, type=int)
    download_parser.add_argument("name", choices=state.get_all_names(), default=None, nargs="?", help="Download only series determined by name")

    download_specific_parser = add_parser_helper(sub_parsers, "download_specific_chapters", aliases=["download"], help="Used to download specific chapters")
    download_specific_parser.add_argument("--stream-index", "-q", default=0, type=int)
    download_specific_parser.add_argument("name", choices=state.get_all_single_names())
    download_specific_parser.add_argument("start", type=float, default=0, help="Starting chapter (inclusive)")
    download_specific_parser.add_argument("end", type=float, nargs="?", default=0, help="Ending chapter (inclusive)")

    # media consumption

    bundle_parser = add_parser_helper(sub_parsers, "bundle-unread-chapters", aliases=["bundle"], help="Bundle individual manga pages into a single file")
    bundle_parser.add_argument("--ignore-errors", "-i", default=False, action="store_const", const=True)
    bundle_parser.add_argument("--limit", "-l", default=0, type=int)
    bundle_parser.add_argument("--shuffle", "-s", default=False, action="store_const", const=True)
    bundle_parser.add_argument("name", choices=state.get_all_names(MediaType.MANGA), default=None, nargs="?")

    read_parser = add_parser_helper(sub_parsers, "read_bundle", aliases=["read"], help="Open a saved bundle for reading. If the command exits with status 0, then the container chapters will be marked read")
    read_parser.add_argument("name", default=None, nargs="?", choices=state.bundles.keys(), help="Name of the bundle")

    sub_consume_parsers = argparse.ArgumentParser(add_help=False)
    sub_consume_parsers.add_argument("--abs", default=False, action="store_const", const=True, dest="force_abs")
    sub_consume_parsers.add_argument("--any-unread", "-a", default=False, action="store_const", const=True)
    sub_consume_parsers.add_argument("--force", "-f", default=False, action="store_const", const=True)
    sub_consume_parsers.add_argument("--limit", "-l", default=0, type=int)
    sub_consume_parsers.add_argument("--shuffle", "-s", default=False, action="store_const", const=True)
    sub_consume_parsers.add_argument("--stream-index", "-q", default=0, type=int)

    view_parser = add_parser_helper(sub_parsers, "view", func_str="play", parents=[sub_consume_parsers], help="View pages of chapters")
    view_parser.add_argument("name", choices=state.get_all_names(MediaType.MANGA | MediaType.NOVEL), default=None, nargs="?")
    view_parser.add_argument("num_list", default=None, nargs="*", type=float)
    view_parser.set_defaults(media_type=MediaType.MANGA | MediaType.NOVEL)

    play_parser = add_parser_helper(sub_parsers, "play", parents=[sub_consume_parsers], help="Either stream anime or directly play downloaded media")
    play_parser.add_argument("name", choices=state.get_all_names(MediaType.ANIME), default=None, nargs="?")
    play_parser.add_argument("num_list", default=None, nargs="*", type=float)
    play_parser.set_defaults(media_type=MediaType.ANIME)

    consume_parser = add_parser_helper(sub_parsers, "consume", func_str="play", parents=[sub_consume_parsers], help="Either view or play media depending on type")
    consume_parser.add_argument("--media-type", choices=list(MediaType), type=MediaType.__getattr__, help="Filter for a specific type")
    consume_parser.add_argument("name", choices=state.get_all_names(MediaType.ANIME), default=None, nargs="?")
    consume_parser.add_argument("num_list", default=None, nargs="*", type=float)

    steam_parser = add_parser_helper(sub_parsers, "stream", help="Streams anime; this won't download any files; if the media is already downloaded, it will be used directly")
    steam_parser.add_argument("--cont", "-c", default=False, action="store_const", const=True)
    steam_parser.add_argument("--download", "-d", default=False, action="store_const", const=True)
    steam_parser.add_argument("--offset", type=float, default=0, help="Offset the url by N chapters")
    steam_parser.add_argument("--stream-index", "-q", default=0, type=int)
    steam_parser.add_argument("url")

    stream_url_parser = add_parser_helper(sub_parsers, "get-stream-url", help="Gets the steaming url for the media")
    stream_url_parser.add_argument("--abs", default=False, action="store_const", const=True, dest="force_abs")
    stream_url_parser.add_argument("--limit", "-l", default=0, type=int)
    stream_url_parser.add_argument("name", choices=state.get_all_names(MediaType.ANIME), default=None, nargs="?")
    stream_url_parser.add_argument("num_list", default=None, nargs="*", type=float)

    # clean
    clean_parser = add_parser_helper(sub_parsers, "clean", help="Removes unused media")
    clean_parser.add_argument("--bundles", "-b", default=False, action="store_const", const=True, help="Removes bundle info")
    clean_parser.add_argument("--include-local-servers", default=False, action="store_const", const=True, help="Doesn't skip local servers")
    clean_parser.add_argument("--remove-disabled-servers", default=False, action="store_const", const=True, help="Removes all servers not belonging to the active list")
    clean_parser.add_argument("--remove-not-on-disk", default=False, action="store_const", const=True, help="Removes references where the backing directory is emtpy")
    clean_parser.add_argument("--remove-read", default=False, action="store_const", const=True, help="Removes all read chapters")
    clean_parser.add_argument("--url-cache", default=False, action="store_const", const=True, help="Clears url cache")

    # external

    auto_import_parser = add_parser_helper(sub_parsers, "auto-import", func_str="auto-import-media")
    auto_import_parser.add_argument("--link", action="store_const", const=True, default=False, help="Hard links instead of just moving the file")

    import_parser = add_parser_helper(sub_parsers, "import", func_str="import-media", help="Import local media into amt")
    import_parser.add_argument("--link", action="store_const", const=True, default=False, help="Hard links instead of just moving the file")
    import_parser.add_argument("--media-type", default="ANIME", choices=list(MediaType), type=MediaType.__getattr__, help="Filter for a specific type")
    import_parser.add_argument("--name", default=None, nargs="?", help="Name Media")
    import_parser.add_argument("--skip-add", action="store_const", const=True, default=False, help="Don't auto add media")
    add_file_completion(import_parser.add_argument("files", nargs="+"))

    # info
    list_parser = add_parser_helper(sub_parsers, "list", func_str="list-media", parents=[readonly_parsers], help="List added media")
    list_parser.add_argument("--csv", action="store_const", const=True, default=False, help="List in a script friendly format")
    list_parser.add_argument("--media-type", default=None, choices=list(MediaType), type=MediaType.__getattr__, help="Filter for a specific type")
    list_parser.add_argument("--out-of-date-only", default=False, action="store_const", const=True)
    list_parser.add_argument("--tag", const="", nargs="?")
    list_parser.add_argument("--tracked", action="store_const", const=True, default=None)
    list_parser.add_argument("--untracked", action="store_const", const=False, dest="tracked", default=None)
    list_parser.add_argument("name", nargs="?", default=None, choices=state.get_server_ids())

    chapter_parsers = add_parser_helper(sub_parsers, "list-chapters", parents=[readonly_parsers], help="List chapters of media")
    chapter_parsers.add_argument("--show-ids", action="store_const", const=True, default=False)
    chapter_parsers.add_argument("name", choices=state.get_all_names())

    add_parser_helper(sub_parsers, "list-servers", help="List enabled servers")

    list_from_servers = add_parser_helper(sub_parsers, "list_some_media_from_server", aliases=["list-from-servers"], help="list some available media from the specified server")
    list_from_servers.add_argument("--limit", "-l", type=int, default=None)
    list_from_servers.add_argument("server_id", choices=state.get_server_ids())

    tag_parser = add_parser_helper(sub_parsers, "tag", help="Apply an arbitrary label")
    tag_parser.add_argument("tag_name")
    tag_parser.add_argument("name", choices=state.get_all_names(), default=None, nargs="?")

    untag_parser = add_parser_helper(sub_parsers, "untag", help="Remove a previously applied label")
    untag_parser.add_argument("tag_name")
    untag_parser.add_argument("name", choices=state.get_all_names(), default=None, nargs="?")

    # credentials
    login_parser = add_parser_helper(sub_parsers, "login", description="Relogin to all servers")
    login_parser.add_argument("--force", "-f", action="store_const", const=True, default=False, help="Force re-login")
    login_parser.add_argument("server_ids", default=None, choices=[[]] + state.get_server_ids_with_logins(), nargs="*")

    # stats
    stats_parser = add_parser_helper(sub_parsers, "stats", func_str="list_stats", description="Show tracker stats", parents=[readonly_parsers])
    stats_parser.add_argument("--details-type", "-d", choices=list(Details), type=Details.__getattr__, default=Details.NO_DETAILS, help="How details are displayed")
    stats_parser.add_argument("--details-limit", "-l", type=int, default=None, help="How many details are shown")
    stats_parser.add_argument("--media-type", choices=list(MediaType), type=MediaType.__getattr__, help="Filter for a specific type")
    stats_parser.add_argument("--min-count", "-m", type=int, default=0, help="Ignore groups with fewer than N elements")
    stats_parser.add_argument("--min-score", type=float, default=1, help="Ignore entries with score less than N")
    stats_parser.add_argument("--sort-index", "-s", choices=list(SortIndex), type=SortIndex.__getattr__, default=SortIndex.SCORE.name, help="Choose sort index")
    stats_parser.add_argument("--no-header", action="store_const", const=True, default=False)
    stats_parser.add_argument("--stat-group", "-g", choices=list(StatGroup), type=StatGroup.__getattr__, default=StatGroup.NAME, help="Choose stat grouping")
    stats_parser.add_argument("--time-unit", "-t", choices=list(TimeUnit), type=TimeUnit.__getattr__, default=TimeUnit.HOURS, help="Choose time unit")

    stats_parser.add_argument("username", default=None, nargs="?", help="Username or id to load info of; defaults to the currently authenticated user")

    stats_update_parser = add_parser_helper(sub_parsers, "stats-update", description="Update tracker stats")
    stats_update_parser.add_argument("--user-id", default=None, help="id to load tracking info of")
    stats_update_parser.add_argument("username", default=None, nargs="?", help="Username to load info of; defaults to the currently authenticated user")

    # trackers and progress
    load_parser = add_parser_helper(sub_parsers, "load_from_tracker", aliases=["load"], parents=[sub_search_parsers], description="Attempts to add all tracked media")
    load_parser.add_argument("--force", "-f", action="store_const", const=True, default=False, help="Force set of read chapters to be in sync with progress")
    load_parser.add_argument("--local-only", action="store_const", const=True, default=False, help="Only attempt to find a match among local media")
    load_parser.add_argument("--no-add", action="store_const", const=True, default=False, help="Don't search for and add new media")
    load_parser.add_argument("--remove", action="store_const", const=True, default=False, help="Remove media that was tracked but no longer active on tracker")
    load_parser.add_argument("--user-id", default=None, nargs="?", help="id to load tracking info of")
    load_parser.add_argument("user_name", default=None, nargs="?", help="Username to load tracking info of; defaults to the currently authenticated user")

    untrack_paraser = add_parser_helper(sub_parsers, "remove_tracker", aliases=["untrack"], help="Removes tracker info")
    untrack_paraser.add_argument("--media-type", choices=list(MediaType), type=MediaType.__getattr__, help="Filter for a specific type")
    untrack_paraser.add_argument("name", choices=state.get_all_single_names(), nargs="?", help="Media to untrack")

    copy_tracker_parser = add_parser_helper(sub_parsers, "copy-tracker", help="Copies tracking info from src to dest")
    copy_tracker_parser.add_argument("src", choices=state.get_all_single_names(), help="Src media")
    copy_tracker_parser.add_argument("dst", choices=state.get_all_single_names(), help="Dst media")

    sync_parser = add_parser_helper(sub_parsers, "sync_progress", aliases=["sync"], help="Update tracker with current progress")
    sync_parser.add_argument("--dry-run", action="store_const", const=True, default=False, help="Don't actually update trackers")
    sync_parser.add_argument("--force", "-f", action="store_const", const=True, default=False, help="Allow progress to decrease")
    sync_parser.add_argument("--media-type", choices=list(MediaType), type=MediaType.__getattr__, help="Filter for a specific type")
    sync_parser.add_argument("name", choices=state.get_all_names(), nargs="?", help="Media to sync")

    mark_unread_parsers = add_parser_helper(sub_parsers, "mark-unread", help="Mark all known chapters as unread")
    mark_unread_parsers.add_argument("--media-type", choices=list(MediaType), type=MediaType.__getattr__, help="Filter for a specific type")
    mark_unread_parsers.add_argument("name", default=None, choices=state.get_all_names(), nargs="?")
    mark_unread_parsers.set_defaults(func_str="mark_read", force=True, N=-1, abs=True)

    mark_parsers = add_parser_helper(sub_parsers, "mark-read", help="Mark all known chapters as read")
    mark_parsers.add_argument("--abs", action="store_const", const=True, default=False, help="Treat N as an abs number")
    mark_parsers.add_argument("--progress", action="store_const", const=True, default=False, help="Use the current saved progress as N")
    mark_parsers.add_argument("--force", "-f", action="store_const", const=True, default=False, help="Allow chapters to be marked as unread")
    mark_parsers.add_argument("--media-type", choices=list(MediaType), type=MediaType.__getattr__, help="Filter for a specific type")
    mark_parsers.add_argument("name", default=None, choices=state.get_all_names(), nargs="?")
    mark_parsers.add_argument("N", type=int, default=0, nargs="?", help="Consider the last N chapters as not up-to-date")

    offset_parser = add_parser_helper(sub_parsers, "offset", help="Adjust server chapter numbers")
    offset_parser.add_argument("name", default=None, choices=state.get_all_names())
    offset_parser.add_argument("offset", type=int, default=None, nargs="?", help="Decrease the chapter number reported by the server by N; specify 0 to reset")

    # upgrade state
    add_parser_helper(sub_parsers, "upgrade-state", aliases=["upgrade"], help="Upgrade old state to newer format")

    # store password state
    set_password_parser = add_parser_helper(sub_parsers, "set-password", help="Set password for a server")
    set_password_parser.add_argument("server_id", choices=state.get_server_ids_with_logins())
    set_password_parser.add_argument("username")
    set_password_parser.set_defaults(func=state.settings.store_credentials)

    auth_parser = add_parser_helper(sub_parsers, "auth", help="Authenticate to a tracker")
    auth_parser.add_argument("--just-print", action="store_const", const=True, default=False, help="Just print the auth url")
    auth_parser.add_argument("tracker_id", choices=state.get_server_ids_with_logins(), nargs="?")

    gen_auto_complete(parser)

    namespace = parser.parse_args(args)
    logging.getLogger().setLevel(namespace.log_level)
    if namespace.tmp_dir:
        state.settings.set_tmp_dir()
        namespace.no_save = True

    action = namespace.type
    kwargs = {k: v for k, v in vars(namespace).items() if k not in SPECIAL_PARAM_NAMES}
    obj = state
    if not "readonly" in namespace:
        # Import only when needed because the act of importing is slow
        from .media_reader_cli import MediaReaderCLI
        media_reader = media_reader if media_reader else MediaReaderCLI(state)
        if state.is_out_of_date_minor():
            media_reader.upgrade_state()
        if namespace.clear_cookies:
            media_reader.session.cookies.clear()
        obj = media_reader
        media_reader.auto_select = namespace.auto
    else:
        namespace.no_save = True
    try:
        if action:
            func = namespace.func if "func" in namespace else getattr(obj, (namespace.func_str if "func_str" in namespace else action).replace("-", "_"))
            ret = func(**kwargs)
            return 1 if ret is False else 0
    finally:
        if not namespace.no_save and ("dry_run" not in namespace or not namespace.dry_run):
            state.save()
