import os
import re

volume_regex = re.compile(r"(_|\s)?vol[ume-]*[\w\s]*(\d+)")


base_media_regex = r"(\([^\)]+\)|\[[^\]]+\]|\d+[.-:]?)?\s*([\w\-]+\w+[\w';:\. ]*\w[!?]*( - [A-Z][A-z]*\d*)?)"
media_dir_regex = re.compile(base_media_regex)
media_file_regex = re.compile(base_media_regex + "(.*\.\w+)$")
number_regex = re.compile(r"(\d+\.?\d*)(?:\s|\.|v\d|$)")

remove_brackets_regex = re.compile(r"(\([^\)]+\)|\[[^\]]+\])")

id_formatter_regex = re.compile(r"\W+")


def get_media_name_from_file(file_name, fallback_name=None, is_dir=True):
    base_name = os.path.basename(file_name if file_name[-1] != "/" else file_name[:-1])
    match = (media_dir_regex if is_dir else media_file_regex).search(volume_regex.sub("", base_name.replace("_", " ")))
    return match.group(2) if match else fallback_name if fallback_name else base_name


def get_media_id_from_name(media_name):
    return id_formatter_regex.sub("_", media_name)


def get_number_from_file_name(file_name, media_name="", default_num=0):
    matches = number_regex.findall(remove_brackets_regex.sub("", file_name.replace(media_name, "").replace("_", " ")))
    return float(max(matches, key=len)) if matches else default_num


def get_alt_names(media_name):
    return list(filter(lambda x: len(x) > min(2, len(media_name)) or x == media_name, dict.fromkeys([media_name, media_name.split(" Season")[0], re.sub(r"\W*$", "", media_name), re.sub(r"[^\w\s]", "", media_name).split()[-1], re.sub(r"\s*[^\w\d\s]+.*$", "", media_name), re.sub(r"(The |A |That |\W.*$)", "", media_name), get_media_name_from_file(media_name, is_dir=True)])))


def find_media_with_similar_name_in_list(media_names, media_list):
    media_names = list(map(str.lower, media_names))
    for media_data in media_list:
        if any(map(lambda name: name in media_data["name"].lower() or ("season_title" in media_data and name in media_data["season_title"].lower()) or media_data["name"].lower() in name, media_names)):
            yield media_data
