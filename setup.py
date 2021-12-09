from distutils.core import setup

setup(name="amt",
      author="Arthur Williams",
      description="Anime/Manga/Novel viewer/tracker",
      packages=["amt", "amt/servers", "amt/trackers", "amt/util"],
      data_files=[("/usr/share/amt", ["scripts/auto_replace.sh", "scripts/merge_ts_files.sh"])],
      scripts=["scripts/amt"],
      url="https://github.com/TAAPArthur/amt",
      version=".9",
      )
