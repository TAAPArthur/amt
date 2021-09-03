from collections import defaultdict
from enum import Enum


class BaseEnum(Enum):

    def __str__(self):
        return self.name


class StatGroup(BaseEnum):
    NAME = 0
    YEAR = 1
    DECADE = 2
    SEASON = 3
    GENRE = 4
    TAG = 5
    STUDIO = 6
    STUDIO_SEP = 7
    ALL = 8


class SortIndex(BaseEnum):
    NAME = 0
    COUNT = 1
    SCORE = 2
    TIME = 3
    WSCORE = 4


class Details(BaseEnum):
    NAME = 0
    YEAR = 1
    SEASON = 2
    GENRE = 3
    TAGS = 4
    STUDIO = 5


def group_entries(media_list, min_score=1):
    tagData = defaultdict(list)
    genereData = defaultdict(list)
    seasonData = defaultdict(list)
    yearData = defaultdict(list)
    studioData = defaultdict(list)
    studioSepData = defaultdict(list)
    decadeData = defaultdict(list)
    allData = defaultdict(list)
    for media in media_list:
        if media["score"] >= min_score and (media["progress"] or media["progressVolumes"]):
            [tagData[x].append(media) for x in media["tags"]]
            [genereData[x].append(media) for x in media["genres"]]
            yearData[str(media["year"])].append(media)
            decadeData[str(int(media["year"] / 10) * 10)].append(media)
            seasonData[media["season"]].append(media)
            studioData[",".join(sorted(media["studio"]))].append(media)
            [studioSepData[x].append(media) for x in media["studio"]]
            allData["All"].append(media)
    return {x["name"]: [x] for x in media_list}, yearData, decadeData, seasonData, genereData, tagData, studioData, studioSepData, allData


def compute_stats(media_map, sortIndex, reverse=True, min_count=0, details=False, details_type=Details.NAME):
    stats = []
    for key, media_list in media_map.items():
        count = len(media_list)
        if count >= min_count:
            avgScore = sum([media["score"] for media in media_list]) / count
            totalTime = sum([media["timeSpent"] for media in media_list])
            weightedScore = sum([media["score"] * media["timeSpent"] / totalTime for media in media_list]) if totalTime else 0
            media_names = ", ".join(map(lambda x: str(x[details_type.name.lower()]), sorted(media_list, key=lambda x: x["score"], reverse=not reverse))) if details else None
            stats.append((key, count, avgScore, totalTime / 60, weightedScore, media_names))
    stats.sort(key=lambda x: x[sortIndex], reverse=not reverse)
    return stats


def get_header_str(statGroup, details=False, details_type=Details.NAME):
    return f"{statGroup.name:50.50}\t" + "\t".join(list(map(lambda x: x.name, SortIndex))[1:]) + (f"\t{details_type.name}" if details else "")


def get_entry_str(entry, details=False):
    return "{:50.50}\t{:5}\t{:5.2f}\t{:5.1f}\t{:5.2f}".format(entry[0], entry[1], entry[2], entry[3], entry[4]) + (f"\t{entry[-1]}" if details else "")
