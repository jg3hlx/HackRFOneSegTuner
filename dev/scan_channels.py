#!/usr/bin/env python3
"""Analyze hackrf_sweep data to find ISDB-T channels."""
import csv
import sys
from collections import defaultdict

ISDB_T_CHANNELS = {}
for ch in range(13, 63):
    center = 473.143e6 + (ch - 13) * 6e6
    ISDB_T_CHANNELS[ch] = (center - 3e6, center + 3e6, center)

channel_power = defaultdict(list)

with open("/tmp/sweep_full.csv") as f:
    reader = csv.reader(f)
    for row in reader:
        if len(row) < 7:
            continue
        try:
            freq_low = float(row[2].strip())
            freq_high = float(row[3].strip())
            powers = [float(p.strip()) for p in row[6:]]
        except (ValueError, IndexError):
            continue

        bin_width = (freq_high - freq_low) / len(powers)
        for i, pwr in enumerate(powers):
            freq = freq_low + bin_width * (i + 0.5)
            for ch, (lo, hi, center) in ISDB_T_CHANNELS.items():
                if lo <= freq <= hi:
                    channel_power[ch].append(pwr)

results = []
for ch, powers in sorted(channel_power.items()):
    if powers:
        avg = sum(powers) / len(powers)
        peak = max(powers)
        results.append((ch, avg, peak, ISDB_T_CHANNELS[ch][2]))

results.sort(key=lambda x: x[1], reverse=True)

print(f"{'Ch':>4} {'Avg dB':>8} {'Peak dB':>8} {'Center MHz':>12}")
print("-" * 36)
for ch, avg, peak, center in results[:15]:
    print(f"{ch:4d} {avg:8.1f} {peak:8.1f} {center/1e6:12.3f}")
