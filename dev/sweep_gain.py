#!/usr/bin/env python3
"""Sweep gain settings and check signal quality."""
import numpy as np
import sys, time
from gnuradio import gr, blocks
import osmosdr

SAMP_RATE = 8e6 * 64 / 63
ch = int(sys.argv[1]) if len(sys.argv) > 1 else 32
freq = 473.143e6 + (ch - 13) * 6e6
NFFT = 4096
duration = 2

configs = [
    # (amp, if_gain, bb_gain)
    (True,  0,   16),
    (True,  8,   16),
    (True,  16,  16),
    (True,  16,  24),
    (True,  24,  16),
    (True,  24,  24),
    (False, 16,  40),
    (False, 24,  40),
    (False, 32,  40),
    (False, 40,  40),
    (False, 40,  62),
]

print(f"ch{ch} ({freq/1e6:.3f} MHz) - Gain sweep")
print(f"{'Config':>25} | {'Max':>6} {'Mean':>6} {'SNR':>5} {'Clip':>5}")
print("-" * 60)

for amp, ig, bg in configs:
    outfile = f"/tmp/gain_test.cf32"
    tb = gr.top_block()
    src = osmosdr.source(args="numchan=1 hackrf=0")
    src.set_sample_rate(SAMP_RATE)
    src.set_center_freq(freq)
    if amp:
        src.set_gain(14, 'RF', 0)
    else:
        src.set_gain(0, 'RF', 0)
    src.set_gain(ig, 'IF', 0)
    src.set_gain(bg, 'BB', 0)

    head = blocks.head(gr.sizeof_gr_complex, int(SAMP_RATE * duration))
    sink = blocks.file_sink(gr.sizeof_gr_complex, outfile, False)
    tb.connect(src, head, sink)
    tb.start()
    tb.wait()

    data = np.fromfile(outfile, dtype=np.complex64)
    mag = np.abs(data)
    max_mag = mag.max()
    mean_mag = mag.mean()
    clip = (mag > 1.4).sum() / len(mag) * 100

    nblocks = len(data) // NFFT
    psd = np.zeros(NFFT)
    for i in range(min(nblocks, 100)):
        block = data[i*NFFT:(i+1)*NFFT]
        psd += np.abs(np.fft.fftshift(np.fft.fft(block * np.hanning(NFFT))))**2
    psd /= min(nblocks, 100)
    psd_db = 10 * np.log10(psd + 1e-20)
    freqs = np.linspace(-SAMP_RATE/2, SAMP_RATE/2, NFFT) / 1e6

    isdb_power = psd_db[np.abs(freqs) < 2.5].mean()
    noise_power = psd_db[np.abs(freqs) > 3.5].mean()
    snr = isdb_power - noise_power

    label = f"{'AMP' if amp else 'noamp'} IF={ig:2d} BB={bg:2d}"
    print(f"{label:>25} | {max_mag:6.3f} {mean_mag:6.3f} {snr:5.1f} {clip:4.1f}%")
    sys.stdout.flush()
    time.sleep(0.2)
