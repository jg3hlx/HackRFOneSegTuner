#!/bin/bash
# Rebuild all content TS files with current inject_si.py settings.
# Uses cached raw TS in /tmp if available, otherwise encodes from source.
#
# Usage: ./build_all.sh [channel]

set -e
cd "$(dirname "$0")"

CH="${1:-13}"

for NUM in 1 2 3; do
    RAW_O="/tmp/oneseg${NUM}_raw.ts"
    RAW_F="/tmp/fullseg${NUM}_raw.ts"

    if [ ! -f "$RAW_O" ] || [ ! -f "$RAW_F" ]; then
        SRC="content/source${NUM}.mp4"
        if [ ! -f "$SRC" ]; then
            echo "=== Skipping #${NUM}: no cache and no source ==="
            continue
        fi
        echo "=== #${NUM}: encoding from source ==="
        ./encode_content.sh "$SRC" "$NUM" "$CH"
        continue
    fi

    echo "=== #${NUM}: rebuilding from cache ==="
    python3 inject_si.py "$RAW_O" /tmp/oneseg${NUM}_si.ts \
        --channel "$CH" --fullseg "$RAW_F"

    python3 -c "
si_pids = {0x0000, 0x0010, 0x0011, 0x0012, 0x0014, 0x0024, 0x1FC8}
with open('$RAW_F', 'rb') as f: data = f.read()
with open('content/fullseg${NUM}.ts', 'wb') as f:
    for i in range(len(data) // 188):
        p = data[i*188:(i+1)*188]
        if p[0] != 0x47: continue
        pid = ((p[1] & 0x1f) << 8) | p[2]
        if pid in si_pids:
            n = bytearray(188)
            n[0]=0x47;n[1]=0x1F;n[2]=0xFF;n[3]=0x10|(i&0xF)
            for j in range(4,188): n[j]=0xFF
            f.write(n)
        else: f.write(p)
"
    python3 -c "
import os
with open('/tmp/oneseg${NUM}_si.ts','rb') as f: a=f.read()
t = os.path.getsize('content/fullseg${NUM}.ts')
with open('content/oneseg${NUM}.ts','wb') as f:
    for _ in range((t//len(a))+1): f.write(a)
"
    rm -f /tmp/oneseg${NUM}_si.ts
    echo "  Done"
done
ls -lh content/{oneseg,fullseg}{1,2,3}.ts 2>/dev/null
