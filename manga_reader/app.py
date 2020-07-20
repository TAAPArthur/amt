from .manga_reader import MangaReader

import logging


class Application(MangaReader):
    auto_select = False

    def print_results(self, results):
        for i, result in enumerate(results):
            print("{:4}| {}:{}\t{}".format(i, result["server_id"], result["id"], result["name"]))

    def select_manga(self, results, prompt):
        index = 0

        print(self.auto_select)
        if not self.auto_select and len(results) > 1:
            index = input(prompt)
        try:
            return results[int(index)]
        except (ValueError, IndexError):
            logging.warning("Invalid input; skipping")
            return None

    def search_add(self, term, exact=False, nosave=False):
        results = self.search_for_manga(term, exact=exact)
        if len(results) == 0:
            logging.warning("Could not find manga %s", term)
            return
        self.print_results(results)

        manga_data = self.select_manga(results, "Select manga to add: ")
        if manga_data:
            self.add_manga(manga_data)
            if not nosave:
                self.save_state()
        return manga_data

    def load_from_tracker(self, user_id=None, user_name=None):
        tracker = self.get_primary_tracker()
        data = tracker.get_tracker_list(id=user_id if user_id else tracker.get_user_info()["id"], user_name=user_name)
        count = 0
        new_count = 0
        for entry in data:
            if entry["anime"]:
                logging.warning("Anime is not yet supported %s", entry)
                continue
            manga_data = self.is_added(entry["id"])
            if not manga_data:

                known_matching_manga = list(filter(lambda x: x["name"].lower() == entry["name"].lower(), self.get_manga_in_library()))
                if known_matching_manga:
                    manga_data = self.select_manga(known_matching_manga, "Select from known manga: ")

                if not manga_data:
                    manga_data = self.search_add(entry["name"], exact=True, nosave=True)
                if not manga_data:
                    continue

                self.settings.track(tracker.id, self._get_global_id(manga_data), entry["id"], entry["name"])
                new_count += 1

            self.mark_chapters_until_n_as_read(manga_data, int(entry["progress"]))
            count += 1
        self.save_state()
        self.list()
        return count, new_count

    def list(self):
        for i, result in enumerate(self.get_manga_in_library()):
            last_chapter_num = self.get_last_chapter_number(result)
            last_read = self.get_last_read(result)
            print("{:4}| {}:{}\t{} {}/{}".format(i, result["server_id"], result["id"], result["name"], last_read, last_chapter_num))

    def list_chapters(self, id):
        results = self.manga[id]["chapters"].values()
        for chapter in results:
            print("{:4}:{}".format(chapter["number"], chapter["title"]))
