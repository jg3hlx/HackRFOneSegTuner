#!/usr/bin/env python3
"""Find ISDB-T scattered pilots to verify signal structure and find correct offset."""
import numpy as np
import sys

iqfile = sys.argv[1] if len(sys.argv) > 1 else "ch19_optimal.cf32"
SAMP_RATE = 8e6 * 64 / 63
N = 8192
CP = 512
SYM_LEN = N + CP
ACTIVE = 5617
ZL = int(np.ceil((N - ACTIVE) / 2.0))

data = np.fromfile(iqfile, dtype=np.complex64, count=SYM_LEN * 100)
print(f"Loaded {len(data)} samples")

# CP detection
search = SYM_LEN * 3
chunk = data[:search]
corr_len = search - N - CP
corr = np.zeros(corr_len, dtype=np.complex128)
for i in range(CP):
    corr += chunk[i:i+corr_len].astype(np.complex128) * np.conj(chunk[i+N:i+N+corr_len].astype(np.complex128))
peak = np.argmax(np.abs(corr))
coarse_freq = np.angle(corr[peak]) / (2 * np.pi) * SAMP_RATE / N
print(f"CP at {peak}, coarse freq: {coarse_freq:.1f} Hz")

# Extract and frequency-correct symbols
nsyms = min(40, (len(data) - peak) // SYM_LEN - 1)
ffts = []
for s in range(nsyms):
    start = peak + s * SYM_LEN + CP
    sym = data[start:start+N].copy()
    t = np.arange(N, dtype=np.float64) + start
    sym *= np.exp(-1j * 2 * np.pi * coarse_freq * t / SAMP_RATE).astype(np.complex64)
    ffts.append(np.fft.fftshift(np.fft.fft(sym)))
ffts = np.array(ffts)

# Generate PRBS
reg = (1 << 11) - 1
prbs = np.zeros(ACTIVE)
for k in range(ACTIVE):
    aux = reg & 1
    new_bit = ((reg >> 2) ^ reg) & 1
    reg = (reg >> 1) | (new_bit << 10)
    prbs[k] = (4 * 2 * (0.5 - aux)) / 3

# Scattered pilot positions for each symbol index
def sp_positions(sym_idx, active_carriers):
    """Return SP carrier positions within active carriers for symbol sym_idx mod 4."""
    positions = []
    start = 3 * (sym_idx % 4)
    for p in range(start, active_carriers, 12):
        positions.append(p)
    return positions

# For each integer offset, check SP correlation
# SP should have boosted power (4/3 amplitude = 16/9 power) and known phase (from PRBS)
print(f"\n--- Scattered Pilot Detection ---")
print(f"{'offset':>6} | {'SP_corr':>8} {'SP_power_ratio':>15}")
print("-" * 40)

best_score = 0
best_off = 0
for off in range(-15, 16):
    zl = ZL + off
    if zl < 0 or zl + ACTIVE > N:
        continue
    carriers = ffts[:, zl:zl+ACTIVE]

    # For each of 4 possible symbol indices, compute SP correlation
    best_sym_corr = 0
    for sym_start in range(4):
        total_corr = 0
        total_power_ratio = 0
        count = 0
        for s in range(nsyms):
            sym_idx = (sym_start + s) % 4
            sp_pos = sp_positions(sym_idx, ACTIVE)
            for p in sp_pos:
                # SP should be prbs[p] * 4/3
                expected = prbs[p] * (4.0/3.0) / (4.0/3.0)  # normalized
                actual = carriers[s, p]
                total_corr += np.real(actual * np.conj(expected * np.abs(actual)))
                count += 1

        avg_corr = total_corr / count if count > 0 else 0
        if avg_corr > best_sym_corr:
            best_sym_corr = avg_corr

    if best_sym_corr > best_score:
        best_score = best_sym_corr
        best_off = off

    if off % 3 == 0 or best_sym_corr > best_score * 0.95:
        print(f"{off:+6d} | {best_sym_corr:8.2f}")

print(f"\nBest offset: {best_off:+d} (corr={best_score:.2f})")

# With best offset, check power distribution
print(f"\n--- Power analysis at offset {best_off:+d} ---")
zl = ZL + best_off
carriers = ffts[:, zl:zl+ACTIVE]
mean_power = np.mean(np.abs(carriers)**2, axis=0)

# Check every 12th carrier (should be SP on some symbols, data on others)
# SP power should be (4/3)^2 = 1.78x data power
for sym_idx in range(4):
    sp_pos = sp_positions(sym_idx, ACTIVE)
    non_sp = [p for p in range(ACTIVE) if p not in sp_pos][:len(sp_pos)*11]

    sp_power_list = []
    data_power_list = []
    for s in range(nsyms):
        actual_sym = (sym_idx + s) % 4
        if actual_sym == sym_idx % 4:
            sp_p = np.mean(np.abs(carriers[s, sp_pos])**2)
            # Use middle carriers as data reference
            mid_carriers = [p for p in range(ACTIVE//3, 2*ACTIVE//3) if p not in sp_pos]
            data_p = np.mean(np.abs(carriers[s, mid_carriers])**2)
            if data_p > 0:
                sp_power_list.append(sp_p / data_p)

    if sp_power_list:
        ratio = np.mean(sp_power_list)
        print(f"  sym_start={sym_idx}: SP/data power ratio = {ratio:.3f} (expected ~1.78)")

# Check if we can see the ISDB-T 13-segment structure
print(f"\n--- Segment structure ---")
seg_width = 432  # carriers per segment in Mode 3
for seg in range(13):
    start_c = seg * seg_width
    end_c = min((seg + 1) * seg_width, ACTIVE)
    if end_c > ACTIVE:
        break
    seg_power = np.mean(mean_power[start_c:end_c])
    bar = '#' * int(seg_power / np.max(mean_power) * 40)
    print(f"  Seg {seg:2d} [{start_c:4d}-{end_c:4d}]: {bar}")

# Check CP carrier (position 0 and ACTIVE-1)
print(f"\n--- Edge carriers ---")
print(f"  Carrier 0 power: {mean_power[0]:.4f}")
print(f"  Carrier {ACTIVE-1} power: {mean_power[ACTIVE-1]:.4f}")
print(f"  Mean data power: {np.mean(mean_power[100:ACTIVE-100]):.4f}")
