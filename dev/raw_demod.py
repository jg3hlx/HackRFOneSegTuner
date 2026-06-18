#!/usr/bin/env python3
"""Raw ISDB-T OFDM demodulator in Python for diagnosis."""
import numpy as np
import sys

iqfile = sys.argv[1] if len(sys.argv) > 1 else "ch19_optimal.cf32"
MODE = 3
N = 2**(10 + MODE)  # 8192
CP_FRAC = 1.0 / 16
CP = int(N * CP_FRAC)  # 512
SYMBOL_LEN = N + CP
ACTIVE = 5617
ZEROS_LEFT = int(np.ceil((N - ACTIVE) / 2.0))

data = np.fromfile(iqfile, dtype=np.complex64, count=SYMBOL_LEN * 200)
print(f"Loaded {len(data)} samples ({len(data)/8.127e6:.2f}s), {len(data)//SYMBOL_LEN} symbols max")

# Step 1: Find CP using ML sync
print("\n--- Step 1: CP Detection ---")
search_len = SYMBOL_LEN * 3
chunk = data[:search_len]
# Compute correlation between x[n] and x[n+N]
corr_len = search_len - N - CP
corr = np.zeros(corr_len, dtype=np.complex128)
for i in range(CP):
    corr += chunk[i:i+corr_len].astype(np.complex128) * np.conj(chunk[i+N:i+N+corr_len].astype(np.complex128))

corr_mag = np.abs(corr)
peak_idx = np.argmax(corr_mag)
print(f"CP correlation peak at sample {peak_idx}, magnitude {corr_mag[peak_idx]:.4f}")
print(f"Coarse freq offset (from CP corr): {np.angle(corr[peak_idx])/(2*np.pi)*8.127e6/N:.1f} Hz")

# Step 2: Extract OFDM symbols and FFT
print("\n--- Step 2: FFT of first 20 symbols ---")
cp_start = peak_idx
fft_data = []
for sym_i in range(20):
    start = cp_start + sym_i * SYMBOL_LEN + CP
    if start + N > len(data):
        break
    symbol = data[start:start+N]
    fft_out = np.fft.fft(symbol)
    # Shift to put DC at center
    fft_shifted = np.fft.fftshift(fft_out)
    fft_data.append(fft_shifted)

fft_data = np.array(fft_data)
print(f"Extracted {len(fft_data)} symbols")

# Step 3: Find active carriers region
print("\n--- Step 3: Find active carriers ---")
mean_power = np.mean(np.abs(fft_data)**2, axis=0)
mean_power_db = 10 * np.log10(mean_power + 1e-20)

# Check expected positions
for offset in range(-5, 6):
    zl = ZEROS_LEFT + offset
    active_power = mean_power_db[zl:zl+ACTIVE].mean()
    guard_l = mean_power_db[max(0,zl-100):zl].mean() if zl > 100 else -99
    guard_r = mean_power_db[zl+ACTIVE:min(N,zl+ACTIVE+100)].mean() if zl+ACTIVE+100 < N else -99
    snr = active_power - max(guard_l, guard_r)
    marker = " <<<" if snr > 15 else ""
    print(f"  offset={offset:+2d}: active={active_power:.1f}dB, guard_L={guard_l:.1f}dB, guard_R={guard_r:.1f}dB, SNR={snr:.1f}dB{marker}")

# Step 4: Try TMCC detection
print("\n--- Step 4: TMCC carrier detection ---")
TMCC_POS = [70, 133, 233, 410, 476, 587, 697, 787, 947, 1033, 1165, 1289, 1319,
            1474, 1537, 1637, 1814, 1880, 1991, 2101, 2191, 2351, 2437, 2569,
            2693, 2723, 2878, 2941, 3041, 3218, 3284, 3395, 3505, 3595, 3755,
            3841, 3973, 4097, 4127, 4282, 4345, 4445, 4622, 4688, 4799, 4909,
            4999, 5159, 5245, 5377, 5501, 5531]

# Generate PRBS
reg = (1 << 11) - 1
prbs = np.zeros(ACTIVE)
for k in range(ACTIVE):
    aux = reg & 1
    new_bit = ((reg >> 2) ^ reg) & 1
    reg = (reg >> 1) | (new_bit << 10)
    prbs[k] = (4 * 2 * (0.5 - aux)) / 3

# Try integer offsets for TMCC correlation
best_corr = 0
best_offset = 0
for offset in range(-15, 16):
    zl = ZEROS_LEFT + offset
    if zl < 0 or zl + ACTIVE > N:
        continue
    active_carriers = fft_data[:, zl:zl+ACTIVE]

    # TMCC correlation
    total = 0
    for sym_i in range(len(active_carriers)):
        corr_val = 0
        for j in range(len(TMCC_POS) - 1):
            t1, t2 = TMCC_POS[j], TMCC_POS[j+1]
            expected_phase_diff = np.sign(prbs[t1]) * np.sign(prbs[t2])
            actual = active_carriers[sym_i, t2] * np.conj(active_carriers[sym_i, t1])
            if expected_phase_diff > 0:
                corr_val += actual
            else:
                corr_val -= actual
        total += abs(corr_val)

    if total > best_corr:
        best_corr = total
        best_offset = offset

    marker = " <<<" if total > best_corr * 0.95 else ""
    if offset % 3 == 0 or abs(total - best_corr) < best_corr * 0.05:
        print(f"  offset={offset:+3d}: TMCC corr={total:.1f}{marker}")

print(f"\nBest integer offset: {best_offset:+d} (corr={best_corr:.1f})")

# Step 5: With best offset, check TMCC DBPSK
print(f"\n--- Step 5: TMCC DBPSK decode (offset={best_offset:+d}) ---")
zl = ZEROS_LEFT + best_offset
active = fft_data[:, zl:zl+ACTIVE]

for t_idx in range(min(5, len(TMCC_POS))):
    pos = TMCC_POS[t_idx]
    phases = np.angle(active[:, pos])
    print(f"  TMCC[{t_idx}] pos={pos}: phases={[f'{p:.2f}' for p in phases[:8]]}")

# Differential decode
tmcc_bits = []
for sym_i in range(1, len(active)):
    bits = []
    for pos in TMCC_POS:
        prev = active[sym_i-1, pos]
        curr = active[sym_i, pos]
        bit = 1 if np.real(curr * np.conj(prev)) < 0 else 0
        bits.append(bit)
    tmcc_bits.append(bits)

if tmcc_bits:
    print(f"\n  First TMCC differential symbols ({len(tmcc_bits)} symbols, {len(TMCC_POS)} carriers each):")
    for i, bits in enumerate(tmcc_bits[:5]):
        print(f"    sym {i}: {''.join(map(str, bits[:26]))}...")

    # Check if first carrier (sync word) shows alternating 0/1 pattern
    sync_bits = [b[0] for b in tmcc_bits]
    print(f"\n  TMCC sync carrier (first carrier differential): {sync_bits[:20]}")
