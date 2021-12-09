import logging

from .media_reader import MediaReader
from .util.media_type import MediaType


class MediaReaderCLI(MediaReader):
    auto_select = False

    def print_results(self, results):
        for i, media_data in enumerate(results):
            print("{:4}| {}\t{} {} ({})".format(i, media_data.global_id, media_data["name"], media_data.get("label", media_data["season_title"]), MediaType(media_data["media_type"]).name))

    def select_media(self, term, results, prompt, no_print=False, auto_select_if_single=False):
        index = 0

        print("Looking for", term)
        if not self.auto_select and not (len(results) == 1 and auto_select_if_single):
            if not no_print:
                self.print_results(results)
            index = input(prompt)
        try:
            return results[int(index)]
        except (ValueError, IndexError):
            logging.warning("Invalid input; skipping")
            return None

    def list_some_media_from_server(self, server_id, limit=None):
        self.print_results(self.get_server(server_id).get_media_list(limit=limit)[:limit])

    def list_servers(self):
        for id in sorted(self.state.get_server_ids()):
            print(id)

    def test_login(self, server_ids=None, force=False):
        failures = False
        for server in self.get_servers():
            if server.has_login() and (not server_ids or server.id in server_ids):
                if (force or server.needs_to_login()) and not server.relogin():
                    logging.error("Failed to login into %s", server.id)
                    failures = True
        return not failures

    def auth(self, tracker_id, just_print=False):
        tracker = self.get_tracker_by_id(tracker_id)
        print("Get token form", tracker.get_auth_url())
        if not just_print:
            self.settings.store_secret(tracker.id, input("Enter token:"))
