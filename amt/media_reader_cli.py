import logging
import os

from . import stats
from .media_reader import MediaReader
from .server import MediaType
from .stats import Details, SortIndex, StatGroup


class MediaReaderCLI(MediaReader):
    auto_select = False

    def print_results(self, results):
        for i, media_data in enumerate(results):
            print("{:4}| {}\t{} {} ({})".format(i, media_data.global_id, media_data["name"], media_data["season_title"], MediaType(media_data["media_type"]).name))

    def select_media(self, term, results, prompt, no_print=False):
        index = 0

        print("Looking for", term)
        if not self.auto_select and len(results) > 1:
            if not no_print:
                self.print_results(results)
            index = input(prompt)
        try:
            return results[int(index)]
        except (ValueError, IndexError):
            logging.warning("Invalid input; skipping")
            return None

    def select_chapter(self, term, quality=0, **kwargs):
        media_data = self.search_add(term, **kwargs, no_add=True)
        if media_data:
            self.update_media(media_data)
            self.list_chapters(media_data)
            chapter = self.select_media(term, media_data.get_sorted_chapters(), "Select episode", no_print=True)
            if chapter:
                return self.play(name=media_data, num_list=[chapter["number"]], force_abs=True, quality=quality)

    def list_servers(self):
        for id in sorted(self.get_servers_ids()):
            print(id)

    def list(self, out_of_date_only=False):
        i = 0
        for media_data in self.get_media():
            last_chapter_num = media_data.get_last_chapter_number()
            last_read = media_data.get_last_read()
            if not out_of_date_only or last_chapter_num != last_read:
                print("{:4}|\t{}\t{} {}\t{}/{}".format(i, media_data.global_id, media_data["name"], media_data["season_title"], last_read, last_chapter_num))
                i = i + 1

    def list_chapters(self, name):
        media_data = self.get_single_media(name=name)
        for chapter in media_data.get_sorted_chapters():
            print("{:4}:{}".format(chapter["number"], chapter["title"]))

    def get_all_names(self, media_type=None, disallow_servers=False):
        names = []
        if not disallow_servers:
            for server_id in self.get_servers_ids():
                if not media_type or self.get_server(server_id).media_type & media_type:
                    names.append(server_id)
        for media_id, media in self.media.items():
            if not media_type or media["media_type"] & media_type:
                names.append(media_id)
                names.append(media["name"])
        return names

    def get_all_single_names(self, media_type=None):
        return self.get_all_names(media_type=media_type, disallow_servers=True)

    def test_login(self, server_ids=None, force=False):
        failures = False
        for server in self.get_servers():
            if server.has_login and (not server_ids or server.id in server_ids):
                if (force or server.needs_to_login()) and not server.relogin():
                    logging.error("Failed to login into %s", server.id)
                    failures = True
        return not failures

    def stats(self, username=None, user_id=None, media_type=None, refresh=False, stat_group=StatGroup.NAME, sort_index=SortIndex.NAME, reverse=False, min_count=0, min_score=1, details=False, details_type=Details.NAME):
        statsFile = self.settings.get_stats_file()
        data = None
        saved_data = self.state.read_file_as_dict(statsFile) if os.path.exists(statsFile) else {}
        if not refresh:
            data = saved_data.get(username if username else "", None)
        if not data:
            logging.info("Loading stats")
            data = list(self.get_primary_tracker().get_full_list_data(id=user_id, user_name=username))
            saved_data.update({username if username else "": data})
            self.state.save_to_file(statsFile, saved_data)
        assert data
        if media_type:
            data = list(filter(lambda x: x["media_type"] == media_type, data))
        grouped_data = stats.group_entries(data, min_score=min_score)[stat_group.value]
        sorted_data = stats.compute_stats(grouped_data, sort_index.value, reverse=reverse, min_count=min_count, details=details, details_type=details_type)
        print("IDX", stats.get_header_str(stat_group, details, details_type=details_type))
        for i, entry in enumerate(sorted_data):
            print(f"{i+1:3} {stats.get_entry_str(entry, details)}")

    def auth(self):
        tracker = self.get_primary_tracker()
        secret = tracker.auth()
        self.settings.store_secret(tracker.id, secret)

    def add_cookie(self, id, name, value, path):
        server = self.get_server(id)
        server.add_cookie(name, value, domain=server.domain, path=path)
