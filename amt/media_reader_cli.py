import logging

from .media_reader import MediaReader


class MediaReaderCLI(MediaReader):
    auto_select = False

    def print_results(self, results):
        for i, data in enumerate(results):
            if isinstance(data, tuple):
                data = "\t".join(map(str, data))
            print("{:4}| {}".format(i, str(data)))

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

    def auth(self, tracker_id, just_print=False):
        tracker = self.get_tracker_by_id(tracker_id)
        print("Get token form", tracker.get_auth_url())
        if not just_print:
            self.settings.store_secret(tracker.id, input("Enter token:"))
