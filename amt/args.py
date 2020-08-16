import argparse
import logging
import os

from .app import Application
from .server import ANIME, MANGA, NOT_ANIME
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
        parser.add_argument('--auto', action="store_const", const=True, default=False, help="Automatically select input instead of prompting")
        parser.add_argument('--clear-cookies', default=False, action="store_const", const=True, help="Clear all cached cookies")
        parser.add_argument('--log-level', default="INFO", choices=logging._levelToName.values(), help="Controls verbosity of logs")
        parser.add_argument('--no-save', default=False, action="store_const", const=True, help="Don't not save state/cookies")
        parser.add_argument('--update', '-u', default=False, action="store_const", const=True, help="Check for new chapters and download them")

        sub_parsers = parser.add_subparsers(dest="type")

        # add remove
        search_parsers = sub_parsers.add_parser("search", description="Search for and add media")
        search_parsers.add_argument('--manga-only', action="store_const", const=MANGA, default=None, help="Filter for Manga")
        search_parsers.add_argument('--anime-only', action="store_const", const=ANIME, default=None, help="Filter for Anime")
        search_parsers.add_argument('--exact', action="store_const", const=True, default=False, help="Only show exact matches")
        search_parsers.add_argument('term', help="The string to search by")

        remove_parsers = sub_parsers.add_parser("remove", description="Remove media")
        remove_parsers.add_argument('id', choices=app.get_media_ids_in_library())

        # update and download
        sub_parsers.add_parser("update")

        sub_parsers.add_parser("download")
        download_parser = sub_parsers.add_parser("download-next")
        download_parser.add_argument('id', choices=app.get_media_ids_in_library())
        download_parser.add_argument('N', type=int, default=100, nargs='?')

        # media consumption
        bundle_parser = sub_parsers.add_parser("bundle")
        bundle_parser.add_argument("-s", '--shuffle', default=False, action="store_const", const=True)
        bundle_parser.add_argument('name', choices=app.get_all_names(MANGA), default=None, nargs='?')

        play_parser = sub_parsers.add_parser("play")
        play_parser.add_argument("-s", '--shuffle', default=False, action="store_const", const=True)
        play_parser.add_argument("-c", '--cont', default=False, action="store_const", const=True)
        play_parser.add_argument('name', choices=app.get_all_names(ANIME), default=None, nargs='?')

        read_parser = sub_parsers.add_parser("read")
        read_parser.add_argument("name", choices=os.listdir(app.settings.bundle_dir))

        # info
        sub_parsers.add_parser("list")
        chapter_parsers = sub_parsers.add_parser("list-chapters")
        chapter_parsers.add_argument('id', choices=app.get_media_ids_in_library())

        # trackers and progress
        sub_parsers.add_parser("auth")

        load_parser = sub_parsers.add_parser("load")
        load_parser.add_argument('name', default=None, nargs='?')
        load_parser.add_argument('--lenient', action="store_const", const=True, default=False)
        load_parser.add_argument('--local-only', action="store_const", const=True, default=False)

        sub_parsers.add_parser("sync").add_argument('--force', default=False)

        mark_parsers = sub_parsers.add_parser("mark-up-to-date")
        mark_parsers.add_argument('--force', default=False)
        mark_parsers.add_argument('N', type=int, default=0, nargs='?')
        mark_parsers.add_argument('server_id', default=None, choices=app.get_servers_ids(), nargs='?')

        # settings
        get_settings_parsers = sub_parsers.add_parser("get")
        get_settings_parsers.add_argument('setting', choices=Settings.get_members())
        set_settings_parsers = sub_parsers.add_parser("set")
        set_settings_parsers.add_argument('setting', choices=Settings.get_members())
        set_settings_parsers.add_argument('value')

        # upgrade state
        sub_parsers.add_parser("upgrade", description="Upgrade old state to newer format")
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

    if namespace.clear_cookies:
        app.session.cookies.clear()
    action = namespace.type
    app.auto_select = namespace.auto
    if action == "auth":
        tracker = app.get_primary_tracker()
        secret = tracker.auth()
        app.settings.store_secret(tracker.id, secret)
    elif action == "bundle":
        print(app.bundle_unread_chapters(name=namespace.name, shuffle=namespace.shuffle))
    elif action == "download":
        app.download_unread_chapters()
    elif action == "download-next":
        app.download_chapters_by_id(namespace.id, namespace.N)
    elif action == "get":
        print("{} = {}".format(namespace.setting, app.settings.get(namespace.setting)))
    elif action == "list":
        app.list()
    elif action == "list-chapters":
        app.list_chapters(namespace.id)
    elif action == "load":
        app.load_from_tracker(user_name=namespace.name, exact=not namespace.lenient, local_only=namespace.local_only)
    elif action == "mark-up-to-date":
        app.mark_up_to_date(namespace.server_id, namespace.N, force=namespace.force)
        app.list()
    elif action == "play":
        print(app.play(name=namespace.name, cont=namespace.cont, shuffle=namespace.shuffle))
    elif action == "read":
        print(app.read_bundle(namespace.name))
    elif action == "remove":
        app.remove_media(id=namespace.id)
    elif action == "search":
        app.search_add(namespace.term, media_type=namespace.manga_only or namespace.anime_only, exact=namespace.exact)
    elif action == "set":
        print("{} = {}".format(namespace.setting, app.settings.set(namespace.setting, namespace.value)))
        app.settings.save()
    elif action == "sync":
        app.sync_progress(namespace.force)
    elif action == "update":
        app.update()
    elif action == "upgrade":
        app.upgrade_state()

    if not namespace.no_save:
        app.save()
