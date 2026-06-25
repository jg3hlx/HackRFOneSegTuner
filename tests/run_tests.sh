#!/bin/bash
# Run all ISDB-T receiver tests.
# Captures fresh IQ data with auto-gain if no test data exists.
set -e
cd "$(dirname "$0")/.."

echo "=== ISDB-T Receiver Test Suite ==="
echo ""

if [ ! -f tests/data/ch23_test.cf32 ]; then
    echo "No test IQ data. Capturing with auto-gain..."
    python3 capture_iq.py 23 --amp --auto-gain --duration 30 -o tests/data/ch23_test.cf32
    echo ""
fi

echo "--- One-seg (Layer A) Tests ---"
python3 -m unittest tests.test_oneseg -v 2>&1
echo ""

echo "--- Full-seg (Layer B) Tests ---"
python3 -m unittest tests.test_fullseg -v 2>&1
echo ""

echo "=== Done ==="
