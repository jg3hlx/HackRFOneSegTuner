#!/usr/bin/env python3
"""Sweep frequency offsets on captured IQ data to find TMCC lock."""
import sys, time, subprocess, re

iqfile = sys.argv[1] if len(sys.argv) > 1 else "ch32_587MHz.cf32"
guard = sys.argv[2] if len(sys.argv) > 2 else "1/16"

offsets = list(range(-30000, 30001, 2000))

print(f"Sweeping {len(offsets)} frequency offsets on {iqfile} (guard={guard})")
print(f"Range: {offsets[0]} to {offsets[-1]} Hz, step 2000 Hz\n")

results = []
for off in offsets:
    cmd = ['python3', 'offline_test.py', iqfile, '--guard', guard, '--freq-offset', str(off)]
    t0 = time.time()
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    dt = time.time() - t0
    combined = proc.stdout + proc.stderr

    tmcc_not_ok = combined.count('TMCC NOT OK')
    tmcc_ok = len(re.findall(r'TMCC parameters.*?:', combined))
    has_params = 'Layer A' in combined or 'layer_a' in combined or 'Mod scheme' in combined

    status = "LOCK" if has_params else f"NOT_OK={tmcc_not_ok}" if tmcc_not_ok > 0 else "none"
    results.append((off, tmcc_not_ok, has_params, dt))
    marker = " <<<< LOCK!" if has_params else (" *" if tmcc_not_ok > 0 else "")
    print(f"  offset={off:+7d} Hz: {status:15s} ({dt:.1f}s){marker}")
    sys.stdout.flush()

print("\n--- Summary ---")
hits = [(off, n, locked) for off, n, locked, _ in results if n > 0 or locked]
if not hits:
    print("No TMCC activity at any offset.")
else:
    print(f"TMCC activity at {len(hits)} offsets:")
    for off, n, locked in hits:
        print(f"  {off:+7d} Hz: {'LOCKED' if locked else f'{n} NOT_OK'}")
