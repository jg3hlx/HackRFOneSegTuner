#!/usr/bin/env python3
"""Analyze spectrum of captured IQ data."""
import numpy as np
import sys

iqfile = sys.argv[1] if len(sys.argv) > 1 else "ch32_587MHz.cf32"
SAMP_RATE = 8e6 * 64 / 63
NFFT = 8192

data = np.fromfile(iqfile, dtype=np.complex64, count=int(SAMP_RATE * 2))
print(f"Loaded {len(data)} samples ({len(data)/SAMP_RATE:.2f}s)")
print(f"Mean magnitude: {np.abs(data).mean():.6f}")
print(f"Max magnitude: {np.abs(data).max():.6f}")
print(f"DC offset: real={data.real.mean():.6f} imag={data.imag.mean():.6f}")

# Power spectrum
from numpy.fft import fftshift, fft
nblocks = len(data) // NFFT
psd = np.zeros(NFFT)
for i in range(nblocks):
    block = data[i*NFFT:(i+1)*NFFT]
    psd += np.abs(fftshift(fft(block * np.hanning(NFFT))))**2
psd /= nblocks
psd_db = 10 * np.log10(psd + 1e-20)
freqs = np.linspace(-SAMP_RATE/2, SAMP_RATE/2, NFFT) / 1e6

# ASCII spectrum display
bins = 80
step = NFFT // bins
print(f"\nSpectrum ({SAMP_RATE/1e6:.3f} MHz bandwidth):")
print(f"{'Freq (MHz)':>10} | Power")
print("-" * 70)
for i in range(bins):
    f = freqs[i * step + step//2]
    p = psd_db[i*step:(i+1)*step].mean()
    bar_len = max(0, int((p - psd_db.min()) / (psd_db.max() - psd_db.min()) * 50))
    if i % 4 == 0:
        print(f"{f:+10.3f} | {'#' * bar_len}")

# Check power in ISDB-T band vs outside
isdb_mask = (np.abs(freqs) < 2.857)
noise_mask = (np.abs(freqs) > 3.5)
isdb_power = psd_db[isdb_mask].mean()
noise_power = psd_db[noise_mask].mean()
print(f"\nISDB-T band power (±2.857 MHz): {isdb_power:.1f} dB")
print(f"Out-of-band noise (>3.5 MHz):   {noise_power:.1f} dB")
print(f"SNR estimate: {isdb_power - noise_power:.1f} dB")

# Check if signal fills full ISDB-T bandwidth
for edge_mhz in [1.0, 2.0, 2.5, 2.786, 3.0, 3.5, 4.0]:
    mask = (np.abs(freqs) < edge_mhz) & (np.abs(freqs) > edge_mhz - 0.5)
    if mask.any():
        p = psd_db[mask].mean()
        print(f"  Power at ±{edge_mhz:.1f} MHz: {p:.1f} dB")
