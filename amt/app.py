from .manga_reader import MangaReader

import logging


class Application(MangaReader):
    auto_select = False

    def save(self):
        self.save_session_cookies()
        self.save_state()

    def print_results(self, results):
        for i, result in enumerate(results):
            print("{:4}| {}:{}\t{}".format(i, result["server_id"], result["id"], result["name"]))

    def select_media(self, results, prompt):
        index = 0

        if not self.auto_select and len(results) > 1:
            index = input(prompt)
        try:
            return results[int(index)]
        except (ValueError, IndexError):
            logging.warning("Invalid input; skipping")
            return None

    def search_add(self, term, exact=False):
        results = self.search_for_media(term, exact=exact)
        if len(results) == 0:
            logging.warning("Could not find media %s", term)
            return
        self.print_results(results)

        media_data = self.select_media(results, "Select media to add: ")
        if media_data:
            self.add_media(media_data)
        return media_data

    def load_from_tracker(self, user_id=None, user_name=None):
        tracker = self.get_primary_tracker()
        data = tracker.get_tracker_list(user_name=user_name) if user_name else tracker.get_tracker_list(id=user_id)
        count = 0
        new_count = 0
        for entry in data:
            if entry["anime"]:
                logging.warning("Anime is not yet supported %s", entry)
                continue
            media_data = self.is_added(tracker.id, entry["id"])
            if not media_data:

                known_matching_media = list(filter(lambda x: x["name"].lower().replace(" ", "") == entry["name"].lower().replace(" ", ""), self.get_media_in_library()))
                if known_matching_media:
                    logging.debug("Checking among known media")
                    media_data = self.select_media(known_matching_media, "Select from known media: ")

                if not media_data:
                    media_data = self.search_add(entry["name"], exact=True)
                if not media_data:
                    logging.info("Could not find media %s", entry["name"])
                    continue

                self.track(tracker.id, self._get_global_id(media_data), entry["id"], entry["name"])
                new_count += 1
            else:
                logging.debug("Already tracking %s %d", media_data["name"], entry["progress"])

            self.mark_chapters_until_n_as_read(media_data, int(entry["progress"]))
            count += 1
        self.list()
        return count, new_count

    def list(self):
        for i, result in enumerate(self.get_media_in_library()):
            last_chapter_num = self.get_last_chapter_number(result)
            last_read = self.get_last_read(result)
            print("{:4}| {}:{}\t{} {}/{}".format(i, result["server_id"], result["id"], result["name"], last_read, last_chapter_num))

    def list_chapters(self, id):
        results = self.media[id]["chapters"].values()
        for chapter in results:
            print("{:4}:{}".format(chapter["number"], chapter["title"]))

    def get_all_names(self):
        return list(self.get_servers_ids()) + list(self.get_media_ids_in_library()) + [x["name"] for x in self.get_media_in_library()]
