#!/usr/bin/env python3
"""Quick scan: capture 2s from each channel and measure SNR + TMCC activity."""
import numpy as np
import sys, time
from gnuradio import gr, blocks, filter as gr_filter
from gnuradio.fft import window
from gnuradio import isdbt
import osmosdr

MODE = 3
SAMP_RATE = 8e6 * 64 / 63
cps = 96 * 2**(MODE - 1)
NFFT = 4096

ch_start = int(sys.argv[1]) if len(sys.argv) > 1 else 13
ch_end = int(sys.argv[2]) if len(sys.argv) > 2 else 52

print(f"Quick scan ch{ch_start}-{ch_end} (AMP IF=8 BB=16)")
print(f"{'Ch':>3} {'Freq':>10} {'Max':>6} {'SNR':>5} {'TMCC':>6}")
print("-" * 40)

for ch in range(ch_start, ch_end + 1):
    freq = 473.143e6 + (ch - 13) * 6e6
    outfile = "/tmp/qscan.cf32"

    # Capture 2 seconds
    tb = gr.top_block()
    src = osmosdr.source(args="numchan=1 hackrf=0")
    src.set_sample_rate(SAMP_RATE)
    src.set_center_freq(freq)
    src.set_gain(14, 'RF', 0)
    src.set_gain(8, 'IF', 0)
    src.set_gain(16, 'BB', 0)
    head = blocks.head(gr.sizeof_gr_complex, int(SAMP_RATE * 2))
    sink = blocks.file_sink(gr.sizeof_gr_complex, outfile, False)
    tb.connect(src, head, sink)
    tb.start()
    tb.wait()

    data = np.fromfile(outfile, dtype=np.complex64)
    mag = np.abs(data)
    max_mag = mag.max()

    nblocks = len(data) // NFFT
    psd = np.zeros(NFFT)
    for i in range(min(nblocks, 50)):
        block = data[i*NFFT:(i+1)*NFFT]
        psd += np.abs(np.fft.fftshift(np.fft.fft(block * np.hanning(NFFT))))**2
    psd /= min(nblocks, 50)
    psd_db = 10 * np.log10(psd + 1e-20)
    freqs_arr = np.linspace(-SAMP_RATE/2, SAMP_RATE/2, NFFT) / 1e6
    isdb_power = psd_db[np.abs(freqs_arr) < 2.5].mean()
    noise_power = psd_db[np.abs(freqs_arr) > 3.5].mean()
    snr = isdb_power - noise_power

    # TMCC test (run from file)
    import subprocess
    proc = subprocess.run(
        ['python3', 'offline_test.py', outfile, '--guard', '1/16'],
        capture_output=True, text=True, timeout=30
    )
    combined = proc.stdout + proc.stderr
    tmcc_cnt = combined.count('TMCC NOT OK')
    tmcc_ok = 'Layer A' in combined or 'Mod scheme' in combined
    tmcc_str = "LOCK!" if tmcc_ok else f"{tmcc_cnt}" if tmcc_cnt > 0 else "-"

    marker = " <<<" if tmcc_ok or snr > 8 else ""
    print(f"{ch:3d} {freq/1e6:10.3f} {max_mag:6.3f} {snr:5.1f} {tmcc_str:>6}{marker}")
    sys.stdout.flush()
    time.sleep(0.1)
