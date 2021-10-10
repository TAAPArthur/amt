#!/bin/sh -e

REPLACEMENTS_FILE=${XDG_CONFIG_HOME:-$HOME/.config}/amt/replacements.txt
if [ -f "$REPLACEMENTS_FILE" ]; then
    case "$1" in
        *.epub)
            for zipFile; do
                dir=$(mktemp -d)
                unzip -d "$dir" "$zipFile"
                find "$dir" -type f -exec sed -E -i -f "$REPLACEMENTS_FILE" {} \+
                ABS_PATH=$(realpath "$zipFile")
                (cd "$dir"; zip -f -m -MM -r "$ABS_PATH" .)
                rm -rf "$dir"
            done
            ;;
        *)
            sed -E -i -f "$REPLACEMENTS_FILE" "$@"
            ;;
    esac
fi
