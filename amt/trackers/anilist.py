import logging

from ..tracker import Tracker


class Anilist(Tracker):
    id = "Anilist"
    url = "https://graphql.anilist.co"
    get_list_query = """
    query ($name: String, $id: Int) { # Define which variables will be used in the query (id)
      Page (page: 1, perPage: 500) {
          pageInfo {
              total
              currentPage
              lastPage
              hasNextPage
              perPage
          }
          mediaList(userName: $name, userId: $id, status: CURRENT ) {
            id
            mediaId
            status
            score
            progress
            media {
               id
               type
               title {
                 english
                 romaji
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

    auth_url = "https://anilist.co/api/v2/oauth/authorize?client_id={}&response_type=token"
    client_id = 3793

    def _get_access_token(self):
        return self.settings.get_secret(self.id)

    def get_auth_header(self):
        return {"Authorization": "Bearer " + self._get_access_token()}

    def get_user_info(self):
        response = self.session.post(self.url, json={"query": self.viewer_query}, headers=self.get_auth_header())
        logging.debug("UserInfo %s", response.text)
        return response.json()["data"]["Viewer"]

    def get_tracker_list(self, user_name=None, id=None):
        variables = {}
        if user_name:
            variables["name"] = user_name
        elif id:
            variables["id"] = id
        else:
            user_info = self.get_user_info()
            variables["id"] = user_info["id"]
        # Make the HTTP Api request
        response = self.session.post(self.url, json={"query": self.get_list_query, "variables": variables})
        data = response.json()
        return [self.get_media_dict(
            id=x["id"],
            anime=x["media"]["type"] == "ANIME",
            title=x["media"]["title"]["english"] or x["media"]["title"]["romaji"],
            progress=x["progress"]
        ) for x in data["data"]["Page"]["mediaList"]]

    def update(self, list_of_updates):
        if not self._get_access_token():
            logging.error("Access token is not set")
            raise ValueError

        for id, progress in list_of_updates:
            variables = {"id": id, "progress": int(progress)}
            logging.debug("Updating %d to %d", id, int(progress))
            response = self.session.post(self.url, json={"query": self.update_list_query, "variables": variables}, headers=self.get_auth_header())
            logging.debug(response.text)

    def auth(self):
        print("Get token from:", self.auth_url.format(self.client_id))
        return input("Enter token:")
