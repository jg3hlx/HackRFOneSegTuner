#!/bin/bash
# Encode a video for ISDB-T transmission (oneseg + fullseg).
#
# Usage:
#   ./encode_content.sh <input_video> <number> [channel]
#   ./encode_content.sh --h264 <input_video> <number> [channel]
#
# Produces: content/oneseg{N}.ts  content/fullseg{N}.ts

set -e
cd "$(dirname "$0")"

H264=0
if [ "$1" = "--h264" ]; then
    H264=1
    shift
fi

INPUT="$1"
NUM="$2"
CH="${3:-13}"

if [ -z "$INPUT" ] || [ -z "$NUM" ]; then
    echo "Usage: $0 [--h264] <input_video> <number> [channel]"
    exit 1
fi

echo "=== Encoding #${NUM}: ${INPUT} for CH${CH} ==="

# Step 1: One-seg (H.264 320x240, ~400kbps)
echo "[1/5] Encoding one-seg..."
ffmpeg -i "$INPUT" \
  -c:v libx264 -profile:v baseline -level 1.3 \
  -s 320x240 -r 15 -b:v 250k -maxrate 280k -bufsize 560k \
  -c:a aac -b:a 64k -ar 48000 -ac 1 \
  -f mpegts \
  -mpegts_transport_stream_id 0x7fe1 \
  -mpegts_pmt_start_pid 0x1fc8 \
  -mpegts_start_pid 0x1081 \
  -muxrate 400k \
  -y /tmp/oneseg${NUM}_raw.ts 2>/dev/null

# Step 2: Full-seg
if [ "$H264" = "1" ]; then
    echo "[2/5] Encoding full-seg (H.264 1920x1080)..."
    ffmpeg -i "$INPUT" \
      -c:v libx264 -profile:v high -level 4.0 \
      -b:v 12M -maxrate 14M -bufsize 28M \
      -s 1920x1080 -r 30000/1001 -g 30 \
      -c:a aac -b:a 256k -ar 48000 -ac 2 \
      -f mpegts \
      -mpegts_transport_stream_id 0x7fe1 \
      -mpegts_pmt_start_pid 0x1fc8 \
      -mpegts_start_pid 0x0100 \
      -muxrate 16M \
      -y /tmp/fullseg${NUM}_raw.ts 2>/dev/null
else
    echo "[2/5] Encoding full-seg (MPEG-2 1440x1080)..."
    ffmpeg -i "$INPUT" \
      -c:v mpeg2video -profile:v high \
      -b:v 14M -maxrate 15M -bufsize 30M \
      -s 1440x1080 -r 30000/1001 -g 15 \
      -c:a aac -b:a 256k -ar 48000 -ac 2 \
      -f mpegts \
      -mpegts_transport_stream_id 0x7fe1 \
      -mpegts_pmt_start_pid 0x1fc8 \
      -mpegts_start_pid 0x0100 \
      -muxrate 16M \
      -y /tmp/fullseg${NUM}_raw.ts 2>/dev/null
fi

# Step 3: Inject SI tables into one-seg (with fullseg ES in PMT)
echo "[3/5] Injecting SI tables..."
python3 inject_si.py \
  /tmp/oneseg${NUM}_raw.ts /tmp/oneseg${NUM}_si.ts \
  --channel "$CH" --fullseg /tmp/fullseg${NUM}_raw.ts

# Step 4: Strip SI from full-seg (keep only video/audio/null)
echo "[4/5] Stripping SI from full-seg..."
python3 -c "
si_pids = {0x0000, 0x0010, 0x0011, 0x0012, 0x0014, 0x0024, 0x1FC8}
with open('/tmp/fullseg${NUM}_raw.ts', 'rb') as f:
    data = f.read()
with open('content/fullseg${NUM}.ts', 'wb') as f:
    for i in range(len(data) // 188):
        p = data[i*188:(i+1)*188]
        if p[0] != 0x47: continue
        pid = ((p[1] & 0x1f) << 8) | p[2]
        if pid in si_pids:
            n = bytearray(188)
            n[0] = 0x47; n[1] = 0x1F; n[2] = 0xFF; n[3] = 0x10 | (i & 0xF)
            for j in range(4, 188): n[j] = 0xFF
            f.write(n)
        else:
            f.write(p)
"

# Step 5: Extend one-seg to match full-seg length
echo "[5/5] Extending one-seg to match full-seg..."
python3 -c "
import os
with open('/tmp/oneseg${NUM}_si.ts', 'rb') as f:
    a = f.read()
target = os.path.getsize('content/fullseg${NUM}.ts')
with open('content/oneseg${NUM}.ts', 'wb') as f:
    for _ in range((target // len(a)) + 1):
        f.write(a)
"

# Keep raw TS in /tmp as cache for build_all.sh
rm -f /tmp/oneseg${NUM}_si.ts

echo ""
echo "=== Done ==="
ls -lh "content/oneseg${NUM}.ts" "content/fullseg${NUM}.ts"
echo ""
echo "Transmit:"
echo "  python3 isdbt_tx.py --ts-a content/oneseg${NUM}.ts --ts-b content/fullseg${NUM}.ts ${CH} --amp --tx-gain 30 --repeat"
