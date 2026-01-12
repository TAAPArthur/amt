from difflib import SequenceMatcher
import os
import re

media_dir_regex = re.compile(r"(\([^\)]+\)|\[[^\]]+\]|\d+[.-:]?)?\s*([\w\-]+\w+[\w';:\. ]*\w[!?]*( - [A-Z][A-z]*\d*)?)")
number_regex_ending = r"(?:\s|\.|v\d|-|$)"
number_regexes = [r"S\d+E(\d+\.?\d*)", r"(?:\s|E|v|^|/)(\d+\.?\d*)"]
season_regexes = [r"(?:S(\d+)E\d+| (\d+)(?:st|nd|rd|th) Season | Season (\d+))"]
quality_regex = re.compile(r"(\d\d\d?0p)", re.IGNORECASE)

special_regex = re.compile(r"( -|)(Extra|Trailer|OVA)( -|)", re.IGNORECASE)

remove_brackets_regex = re.compile(r"(\([^\)]+\)|\[[^\]]+\])")

id_formatter_regex = re.compile(r"\W+")

media_name_regex = re.compile("(, )?(Vol\.|volume|Volume|Part|) \d+\.?\d*$")

def is_special_episode_from_name(chapter_name):
    return special_regex.search(chapter_name) is not None


def get_media_name_from_file(base_name, is_dir=True):
    match = media_dir_regex.search(base_name)
    return match.group(2) if match else base_name


def get_media_id_from_name(media_name):
    return id_formatter_regex.sub("_", media_name)


def get_media_name_from_volume_name(name):
    name = remove_brackets_regex.sub("", os.path.basename(name if name[-1] != "/" else name[:-1]))
    media_name = os.path.splitext(media_name_regex.split(name)[0].strip())[0]
    media_id = get_media_id_from_name(media_name)
    return media_name, media_id

def get_number_from_file_name_helper(regexes, file_name, media_name="", regex_ending="", default_num=0):
    for regex in regexes:
        print(regex, file_name)
        matches = re.findall(regex + regex_ending, file_name.replace(media_name, "").replace("_", " "), re.IGNORECASE)
        if matches:
            print(matches)
            if isinstance(matches[0], tuple):
                matches=list(map(lambda x: max(x, key=len), matches))
            print(matches)
            num = float(max(matches, key=len))
            return int(num) if num % 1 == 0 else num
    return default_num


def get_number_from_file_name(file_name, media_name="", default_num=0, regex_str=None):
    return get_number_from_file_name_helper(number_regexes if regex_str is None else [regex_str], file_name, media_name=media_name, regex_ending=number_regex_ending, default_num=default_num)


def get_season_number_from_file_name(file_name, media_name="", default_num=0):
    return get_number_from_file_name_helper(season_regexes, file_name, media_name=media_name, default_num=default_num)

def get_quality_from_file_name(file_name):
    matches = quality_regex.findall(file_name)
    return max(matches, key=len) if matches else ""


def get_alt_names(media_name):
    media_name = re.sub("\([^)]*\)", "", media_name).strip()
    return list(filter(lambda x: len(x) > min(2, len(media_name)) or x == media_name, dict.fromkeys([media_name, media_name.split(" Season")[0], re.sub(r"\W*$", "", media_name), re.sub(r"\s*[^\w\d\s]+.*$", "", media_name), re.sub(r"(The |A |That |\W.*$)", "", media_name), get_media_name_from_file(media_name, is_dir=True)])))


def find_media_with_similar_name_in_list(media_names, media_list):
    media_names = list(map(str.lower, media_names))
    for media_data in media_list:
        if any(map(lambda name: name in media_data["name"].lower() or ("season_title" in media_data and name in media_data["season_title"].lower()) or media_data["name"].lower() in name, media_names)):
            yield media_data


def get_season_id(title):
    quality = get_quality_from_file_name(title)
    season_number = get_season_number_from_file_name(title, default_num=None)
    season_id = ("S" + str(season_number)) if season_number is not None else ""
    return season_id + quality

def clean_media_name(name):
    name = name.replace("[END]", "")
    return name

def group_titles_for_same_media_season(title_media_type_list, min_match_len = 3 ):
    keys = list()
    for title, media_type in title_media_type_list:
        keys.append((clean_media_name(title), get_season_id(title), media_type))

    results = set()
    for i, key, in enumerate(keys):
        sample_file, season_id, media_type = key
        best_value = None
        highest_score = 0
        for e, si, mt in keys[i + 1:]:
            if e == sample_file or mt != media_type or si != season_id:
                continue
            if len(e) == len(sample_file):
                seqs = SequenceMatcher(None, e, sample_file).get_matching_blocks()
                if any(map(lambda s: s.a != s.b, seqs)):
                    continue
                total_same = sum([s[-1] for s in seqs])
                if total_same >= len(sample_file) / 2:
                    if total_same > highest_score and seqs[0][2] > min_match_len:
                        highest_score = total_same
                        best_value = seqs[0]

        if best_value is not None:
            matches = best_value
            title = sample_file[matches[0]:matches[2]].strip()
            if " " in title:
                title = " ".join(title.split(" ")[:-1]).strip()
            if title[-1] == "-":
                title = title[:-1].strip()

            k = title, media_type, season_id, len(sample_file)
            if k in results:
                continue
            results.add(k)
            yield sample_file, title, media_type, season_id
