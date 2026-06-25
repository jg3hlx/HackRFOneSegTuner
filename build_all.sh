#!/bin/bash
# Rebuild all content TS files with current inject_si.py settings.
# Sources must exist as content/source{1,2,3}.mp4
#
# Usage: ./build_all.sh [channel]

set -e
cd "$(dirname "$0")"

CH="${1:-13}"

for NUM in 1 2 3; do
    SRC="content/source${NUM}.mp4"
    if [ ! -f "$SRC" ]; then
        echo "=== Skipping #${NUM}: ${SRC} not found ==="
        continue
    fi
    ./encode_content.sh "$SRC" "$NUM" "$CH"
done
