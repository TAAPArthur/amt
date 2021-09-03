from enum import IntFlag


class MediaType(IntFlag):
    def __str__(self):
        return self.name

    @classmethod
    def get(clazz, x, default=None):
        return clazz[x] if x in clazz.__members__ else default
    MANGA = 1
    NOVEL = 2
    ANIME = 4
