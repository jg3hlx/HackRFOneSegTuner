#!/usr/bin/env python3
"""Sweep integer subcarrier offsets to find TMCC lock."""
import subprocess, sys, re

iqfile = sys.argv[1] if len(sys.argv) > 1 else "ch19_optimal.cf32"
SAMP_RATE = 8e6 * 64 / 63
FFT_LEN = 8192
sc_spacing = SAMP_RATE / FFT_LEN  # ~991.8 Hz

print(f"Sweeping subcarrier offsets on {iqfile}")
print(f"Subcarrier spacing: {sc_spacing:.1f} Hz")
print(f"{'SC_off':>6} {'Hz':>8} | {'OK':>4} {'NOT_OK':>7} {'WHAT':>5} {'smooth':>7}")
print("-" * 55)

for sc in range(-15, 16):
    freq_off = sc * sc_spacing
    cmd = ['python3', 'offline_test2.py', iqfile, '--guard', '1/16', '--freq-offset', str(freq_off)]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    combined = proc.stdout + proc.stderr
    tmcc_ok = combined.count('TMCC OK')
    tmcc_not = combined.count('TMCC NOT OK')
    tmcc_what = combined.count('TMCC WHAT')
    smooth = combined.count('smooth channel gain')
    marker = " <<< LOCK!" if tmcc_ok > 0 else (" <<<" if smooth > 0 else "")
    print(f"{sc:+6d} {freq_off:+8.0f} | {tmcc_ok:>4} {tmcc_not:>7} {tmcc_what:>5} {smooth:>7}{marker}")
    sys.stdout.flush()
