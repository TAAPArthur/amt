import os
import re

volume_regex = re.compile(r"(_|\s)?vol[ume-]*[\w\s]*(\d+)")


base_media_regex = r"([\[(][\w ]*[\])]|\d+[.-:]?)?\s*([\w\-]+\w+[\w';:\. ]*\w[!?]*)"
media_dir_regex = re.compile(base_media_regex)
media_file_regex = re.compile(base_media_regex + "(.*\.\w+)$")
number_regex = re.compile(r"(\d+\.?\d*)[ \.]")

id_formatter_regex = re.compile(r"\W+")


def get_media_name_from_file(file_name, fallback_name=None, is_dir=True):
    base_name = os.path.basename(file_name if file_name[-1] != "/" else file_name[:-1])
    match = (media_dir_regex if is_dir else media_file_regex).search(volume_regex.sub("", base_name.replace("_", " ")))
    return match.group(2) if match else fallback_name if fallback_name else base_name


def get_media_id_from_name(media_name):
    return id_formatter_regex.sub("_", media_name)


def get_number_from_file_name(file_name, media_name="", default_num=0):
    matches = number_regex.findall(file_name.replace(media_name, "").replace("_", " "))
    return float(max(matches, key=len)) if matches else default_num
