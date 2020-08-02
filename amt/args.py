import argparse
import logging
import os

from .settings import Settings
from .app import Application


def parse_args(args=None, app=None):

    app = app if app else Application()
    parser = argparse.ArgumentParser()
    parser.add_argument('--no-save', default=False, action="store_const", const=True,)
    parser.add_argument('--log-level', dest="log_level", default="INFO", choices=logging._levelToName.values())

    sub_parsers = parser.add_subparsers(dest="type")
    parser.add_argument('--auto', action="store_const", const=True, default=False)

    search_parsers = sub_parsers.add_parser("search")
    search_parsers.add_argument('arg')

    sub_parsers.add_parser("update")
    sub_parsers.add_parser("download").add_argument('-u', dest="update", default=False, action="store_const", const=True,)
    download_parser = sub_parsers.add_parser("download-next")
    download_parser.add_argument('id', choices=app.get_manga_ids_in_library())
    download_parser.add_argument('N', type=int, default=100, nargs='?')

    sub_parsers.add_parser("bundle").add_argument('name', choices=app.get_all_names(), default=None, nargs='?')
    read_parser = sub_parsers.add_parser("read")
    read_parser.add_argument("name", choices=os.listdir(app.settings.bundle_dir))
    sub_parsers.add_parser("load").add_argument('name', default=None, nargs='?')
    sub_parsers.add_parser("sync-progress").add_argument('--force', default=False)
    sub_parsers.add_parser("list")
    sub_parsers.add_parser("auth")
    chapter_parsers = sub_parsers.add_parser("list-chapters")
    chapter_parsers.add_argument('id', choices=app.get_manga_ids_in_library())

    mark_parsers = sub_parsers.add_parser("mark-up-to-date")
    mark_parsers.add_argument('--force', default=False)
    mark_parsers.add_argument('N', type=int, default=0, nargs='?')
    mark_parsers.add_argument('server_id', default=None, choices=app.get_servers_ids(), nargs='?')

    get_settings_parsers = sub_parsers.add_parser("get")
    get_settings_parsers.add_argument('setting', choices=Settings.get_members())
    set_settings_parsers = sub_parsers.add_parser("set")
    set_settings_parsers.add_argument('setting', choices=Settings.get_members())
    set_settings_parsers.add_argument('value')

    namespace = parser.parse_args(args)
    logging.getLogger().setLevel(namespace.log_level)
    action = namespace.type
    app.auto_select = namespace.auto
    if action == "search":
        app.search_add(namespace.arg)
    elif action == "auth":
        tracker = app.get_primary_tracker()
        secret = tracker.auth()
        app.settings.store_secret(tracker.id, secret)
    elif action == "load":
        app.load_from_tracker(user_name=namespace.name)
    elif action == "sync-progress":
        app.sync_progress(namespace.force)
    elif action == "download":
        if namespace.update:
            app.update()
        app.download_unread_chapters()
    elif action == "download-next":
        app.download_chapters_by_id(namespace.id, namespace.N)
    elif action == "bundle":
        print(app.bundle_unread_chapters(namespace.name))
    elif action == "read":
        print(app.read_bundle(namespace.name))
    elif action == "list":
        app.list()
    elif action == "update":
        app.update()
    elif action == "mark-up-to-date":
        app.mark_up_to_date(namespace.server_id, namespace.N, force=namespace.force)
        app.list()
    elif action == "list-chapters":
        app.list_chapters(namespace.id)
    elif action == "get":
        print("{} = {}".format(namespace.setting, app.settings.get(namespace.setting)))
    elif action == "set":
        print("{} = {}".format(namespace.setting, app.settings.set(namespace.setting, namespace.value)))
        app.settings.save()

    if not namespace.no_save:
        app.save()