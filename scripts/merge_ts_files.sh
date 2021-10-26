#!/bin/sh

if [ $# -gt 1 ] && [ "${1%*.ts}.ts" = "$1" ]; then
    cat "$@" > video.mp4
fi
