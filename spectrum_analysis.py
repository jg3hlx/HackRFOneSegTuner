#!/usr/bin/env python3
"""Analyze full-bandwidth spectrum to visualize HackRF DC offset / passband shape."""
import numpy as np
import sys

iqfile = sys.argv[1] if len(sys.argv) > 1 else "ch19_optimal.cf32"
SAMP_RATE = 8e6 * 64 / 63
N = 8192

data = np.fromfile(iqfile, dtype=np.complex64, count=int(SAMP_RATE * 2))
print(f"Loaded {len(data)} samples ({len(data)/SAMP_RATE:.2f}s)")

nblocks = len(data) // N
avg_psd = np.zeros(N)
for i in range(nblocks):
    block = data[i*N:(i+1)*N]
    spectrum = np.fft.fftshift(np.fft.fft(block * np.hanning(N)))
    avg_psd += np.abs(spectrum)**2
avg_psd /= nblocks
avg_psd_db = 10 * np.log10(avg_psd + 1e-20)

freqs = np.fft.fftshift(np.fft.fftfreq(N, 1/SAMP_RATE)) / 1e6

active_bw = 5617 * SAMP_RATE / N / 1e6
print(f"ISDB-T active bandwidth: {active_bw:.3f} MHz")
print(f"Capture bandwidth: {SAMP_RATE/1e6:.3f} MHz")

print(f"\n--- Full Bandwidth Spectrum (ASCII) ---")
print(f"{'Freq(MHz)':>10} | {'Power':>6} | {'Spectrum'}")
print("-" * 75)

step = N // 64
peak_db = np.max(avg_psd_db)
for i in range(0, N, step):
    f = freqs[i]
    p = avg_psd_db[i:i+step].mean()
    bar_len = max(0, int((p - (peak_db - 40)) / 40 * 50))
    in_active = abs(f) < active_bw / 2
    marker = "|" if in_active else " "
    print(f"{f:+10.3f} | {p:6.1f} | {marker}{'#' * bar_len}")

print(f"\n--- Baseband frequency response (zoomed to active band) ---")
half_active = int(active_bw / 2 / (SAMP_RATE / 1e6) * N) + 50
center = N // 2
zoomed = avg_psd_db[center-half_active:center+half_active]
zoomed_freqs = freqs[center-half_active:center+half_active]
step2 = max(1, len(zoomed) // 40)

peak_active = np.max(zoomed)
print(f"{'Freq(MHz)':>10} | {'dB':>6} | {'Response'}")
print("-" * 65)
for i in range(0, len(zoomed), step2):
    f = zoomed_freqs[i]
    p = zoomed[i:i+step2].mean()
    bar_len = max(0, int((p - (peak_active - 30)) / 30 * 40))
    print(f"{f:+10.3f} | {p:6.1f} | {'#' * bar_len}")

dc_power = avg_psd_db[center-2:center+3].mean()
edge_power = (avg_psd_db[center-half_active:center-half_active+20].mean() +
              avg_psd_db[center+half_active-20:center+half_active].mean()) / 2
print(f"\nDC region power: {dc_power:.1f} dB")
print(f"Edge region power: {edge_power:.1f} dB")
print(f"DC suppression: {edge_power - dc_power:.1f} dB")

oneseg_half = int(432 * 0.5)
center_carrier = N // 2
oneseg_power = avg_psd_db[center_carrier-oneseg_half:center_carrier+oneseg_half].mean()
print(f"One-seg region power: {oneseg_power:.1f} dB")
print(f"One-seg suppression vs edge: {edge_power - oneseg_power:.1f} dB")
