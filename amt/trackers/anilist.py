import logging

from ..server import Tracker
from ..util.media_type import MediaType


class Anilist(Tracker):
    id = "anilist"
    url = "https://graphql.anilist.co"

    get_list_query = """
    query ($name: String, $id: Int, $pageIndex: Int, $status: MediaListStatus) { # Define which variables will be used in the query (id)
        Page(page: $pageIndex, perPage: 50) {
            pageInfo {
              total
              currentPage
              lastPage
              hasNextPage
              perPage
            }
        mediaList(userName: $name, userId: $id, status: $status) {
            id
            mediaId
            status
            score
            progress
            progressVolumes
            repeat
            media {
                seasonYear
                seasonInt
                startDate{year}
                endDate{year}
                season
                episodes
                duration
                nextAiringEpisode {
                  airingAt
                }
                genres
                tags {
                    name
                    rank
                }
                studios {
                    nodes { name }
                    edges { isMain }
                }
                type
                format
                title {
                    english
                    romaji
                }
                externalLinks {
                  url
                }
                streamingEpisodes {
                  url
                }
            }
        }
    }
}
    """
    viewer_query = """
    query{
      Viewer{
        id
        name
      }
    }
    """

    update_list_query = """
    mutation($id: Int, $progress: Int) {
      SaveMediaListEntry(id: $id, progress: $progress) {
        id
        progress
      }
    }
    """

    update_list_query_volumes = """
    mutation($id: Int, $progress: Int) {
      SaveMediaListEntry(id: $id, progressVolumes: $progress) {
        id
        progressVolumes
      }
    }
    """

    auth_url = "https://anilist.co/api/v2/oauth/authorize?client_id={}&response_type=token"
    client_id = 3793

    def _get_access_token(self):
        return self.settings.get_secret(self.id)

    def get_auth_header(self):
        return {"Authorization": "Bearer " + self._get_access_token()}

    def get_user_info(self):
        response = self.session_post(self.url, json={"query": self.viewer_query}, headers=self.get_auth_header())
        self.logger.debug("UserInfo %s", response.text)
        return response.json()["data"]["Viewer"]

    def _get_variables(self, user_name=None, id=None):
        variables = {}
        if user_name:
            variables["name"] = user_name
        elif id:
            variables["id"] = id
        else:
            user_info = self.get_user_info()
            variables["id"] = user_info["id"]
        return variables

    def get_full_list_data(self, user_name=None, id=None):
        return self.get_tracker_list(user_name, id, status=None)

    def get_tracker_list(self, user_name=None, id=None, status="CURRENT"):
        variables = self._get_variables(user_name, id)
        if status:
            variables["status"] = status
        # Make the HTTP Api request
        pageIndex = 1
        while True:
            self.logger.info(f"Loading page {pageIndex}")
            variables["pageIndex"] = pageIndex
            response = self.session_post(self.url, json={"query": self.get_list_query, "variables": variables})
            data = response.json()
            yield from [self.get_media_dict(
                id=x["id"],
                media_type=MediaType.ANIME if x["media"]["type"] == "ANIME" else MediaType.get(x["media"]["format"], MediaType.MANGA),
                progress=x["progress"],
                progress_volumes=x["progressVolumes"],
                names=x["media"]["title"],
                score=x["score"],
                nextTimeStamp=x["media"]["nextAiringEpisode"]["airingAt"] if x["media"]["nextAiringEpisode"] else None,
                time_spent=x["progress"] * x["media"]["duration"] if x["media"]["duration"] else x["progress"] or x["progressVolumes"] or 0,
                year=x["media"]["startDate"]["year"],
                year_end=x["media"]["endDate"]["year"],
                season="{} {}".format(x["media"]["season"], x["media"]["seasonYear"]) if x["media"]["season"] else str(x["media"]["startDate"]["year"]),
                external_links=[url["url"] for url in x["media"]["externalLinks"]],
                streaming_links=[url["url"] for url in x["media"]["streamingEpisodes"]],
                genres=x["media"]["genres"],
                tags=[x["name"] for x in x["media"]["tags"] if x["rank"] > 70],
                studio=[n["name"] for n, e in zip(x["media"]["studios"]["nodes"], x["media"]["studios"]["edges"]) if e["isMain"]] if x["media"]["studios"]["nodes"] else []
            ) for x in data["data"]["Page"]["mediaList"]]
            if data["data"]["Page"]["pageInfo"]["hasNextPage"]:
                pageIndex += 1
            else:
                break

    def update(self, list_of_updates):
        headers = self.get_auth_header()
        for id, progress, progress_volumes in list_of_updates:
            variables = {"id": id, "progress": int(progress)}
            logging.debug("Updating %d to %d, Volume: %d", id, int(progress), progress_volumes)
            query = self.update_list_query_volumes if progress_volumes else self.update_list_query
            response = self.session_post(self.url, json={"query": query, "variables": variables}, headers=headers)
            logging.debug(response.text)

    def get_auth_url(self):
        return self.auth_url.format(self.client_id)
