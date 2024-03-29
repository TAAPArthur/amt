from distutils.core import setup

setup(name="amt",
      author="Arthur Williams",
      description="Anime/Manga/Novel viewer/tracker",
      packages=["amt", "amt/servers", "amt/trackers", "amt/util"],
      scripts=["scripts/amt"],
      url="https://github.com/TAAPArthur/amt",
      version="1",
      )
