#!/usr/bin/env python3
"""Diagnose ISDB-T signal: try all modes, guard intervals, find TMCC."""
import numpy as np
import sys

iqfile = sys.argv[1] if len(sys.argv) > 1 else "ch19_optimal.cf32"
SAMP_RATE = 8e6 * 64 / 63

data = np.fromfile(iqfile, dtype=np.complex64, count=int(SAMP_RATE * 5))
print(f"Loaded {len(data)} samples ({len(data)/SAMP_RATE:.2f}s)")

TMCC_2K = [70, 133, 233, 410, 476, 587, 697, 787, 947, 1033, 1165, 1289, 1319]
TMCC_4K = TMCC_2K + [1474, 1537, 1637, 1814, 1880, 1991, 2101, 2191, 2351, 2437, 2569, 2693, 2723]
TMCC_8K = TMCC_4K + [2878, 2941, 3041, 3218, 3284, 3395, 3505, 3595, 3755, 3841, 3973, 4097, 4127,
                      4282, 4345, 4445, 4622, 4688, 4799, 4909, 4999, 5159, 5245, 5377, 5501, 5531]

def gen_prbs(n):
    reg = (1 << 11) - 1
    vals = np.zeros(n)
    for k in range(n):
        aux = reg & 1
        new_bit = ((reg >> 2) ^ reg) & 1
        reg = (reg >> 1) | (new_bit << 10)
        vals[k] = (4 * 2 * (0.5 - aux)) / 3
    return vals

for mode in [3, 2, 1]:
    N = 2**(10 + mode)
    seg_carriers = 108 * 2**(mode-1)
    active = 1 + 13 * seg_carriers
    zeros_left = int(np.ceil((N - active) / 2.0))

    if mode == 1: tmcc_pos = TMCC_2K
    elif mode == 2: tmcc_pos = TMCC_4K
    else: tmcc_pos = TMCC_8K

    prbs = gen_prbs(active)

    for cp_frac_d in [16, 8, 4, 32]:
        cp_frac = 1.0 / cp_frac_d
        cp_len = int(N * cp_frac)
        sym_len = N + cp_len

        # CP detection
        search = min(len(data), sym_len * 4)
        chunk = data[:search]
        corr_len = search - N - cp_len
        if corr_len <= 0:
            continue
        corr = np.zeros(corr_len, dtype=np.complex128)
        step = max(1, cp_len // 32)
        for i in range(0, cp_len, step):
            corr += chunk[i:i+corr_len].astype(np.complex128) * np.conj(chunk[i+N:i+N+corr_len].astype(np.complex128))
        corr_mag = np.abs(corr)
        peak_idx = np.argmax(corr_mag)
        peak_val = corr_mag[peak_idx]

        # Normalize by signal power
        sig_power = np.mean(np.abs(chunk[:sym_len*2])**2)
        norm_peak = peak_val / (sig_power * (cp_len // step)) if sig_power > 0 else 0

        if norm_peak < 0.3:
            continue

        coarse_freq = np.angle(corr[peak_idx]) / (2 * np.pi) * SAMP_RATE / N

        # Extract symbols with freq correction
        nsyms = min(50, (len(data) - peak_idx) // sym_len - 1)
        if nsyms < 10:
            continue

        fft_data = []
        for s in range(nsyms):
            start = peak_idx + s * sym_len + cp_len
            if start + N > len(data):
                break
            sym = data[start:start+N]
            # Apply coarse frequency correction
            t = np.arange(N) + peak_idx + s * sym_len + cp_len
            sym = sym * np.exp(-1j * 2 * np.pi * coarse_freq * t / SAMP_RATE)
            fft_data.append(np.fft.fftshift(np.fft.fft(sym)))
        fft_data = np.array(fft_data)

        # Try integer offsets - check TMCC majority vote quality
        best_quality = 0
        best_off = 0
        for off in range(-15, 16):
            zl = zeros_left + off
            if zl < 0 or zl + active > N:
                continue
            carriers = fft_data[:, zl:zl+active]

            # Differential DBPSK decode
            qualities = []
            for sym_i in range(1, len(carriers)):
                bits = []
                for pos in tmcc_pos:
                    prev = carriers[sym_i-1, pos]
                    curr = carriers[sym_i, pos]
                    bit = 1 if np.real(curr * np.conj(prev)) < 0 else 0
                    bits.append(bit)
                # Majority vote quality: how many agree?
                ones = sum(bits)
                zeros = len(bits) - ones
                quality = max(ones, zeros) / len(bits)
                qualities.append(quality)

            avg_quality = np.mean(qualities) if qualities else 0
            if avg_quality > best_quality:
                best_quality = avg_quality
                best_off = off

        if best_quality > 0.7:
            print(f"\nMode {mode} Guard 1/{cp_frac_d}: CP peak={norm_peak:.2f} freq_off={coarse_freq:.1f}Hz")
            print(f"  BEST offset={best_off:+d}: TMCC majority vote quality={best_quality:.3f} ({nsyms} symbols)")

            # Decode TMCC bits at best offset
            zl = zeros_left + best_off
            carriers = fft_data[:, zl:zl+active]
            bits_seq = []
            for sym_i in range(1, len(carriers)):
                bits = []
                for pos in tmcc_pos:
                    prev = carriers[sym_i-1, pos]
                    curr = carriers[sym_i, pos]
                    bit = 1 if np.real(curr * np.conj(prev)) < 0 else 0
                    bits.append(bit)
                majority = 1 if sum(bits) > len(bits)/2 else 0
                agree = sum(1 for b in bits if b == majority) / len(bits)
                bits_seq.append((majority, agree))

            print(f"  TMCC bits: {''.join(str(b) for b,_ in bits_seq[:30])}...")
            print(f"  Agreement: {' '.join(f'{a:.0%}'[:3] for _,a in bits_seq[:30])}...")
        elif norm_peak > 0.5:
            print(f"Mode {mode} Guard 1/{cp_frac_d}: CP peak={norm_peak:.2f}, TMCC quality={best_quality:.3f} (too low)")
