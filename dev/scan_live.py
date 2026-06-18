#!/usr/bin/env python3
"""ISDB-T live channel scanner - scans UHF channels for TMCC lock."""
import sys, time, os
from gnuradio import gr, blocks, filter as gr_filter
from gnuradio.fft import window
from gnuradio import isdbt
import osmosdr

MODE = 3
SAMP_RATE = 8e6 * 64 / 63
cps = 96 * 2**(MODE - 1)

amp_enable = '--amp' in sys.argv
ch_start = 13
ch_end = 52

for arg in sys.argv[1:]:
    if arg.startswith('--start='):
        ch_start = int(arg.split('=')[1])
    elif arg.startswith('--end='):
        ch_end = int(arg.split('=')[1])

print(f"Scanning ch{ch_start}-{ch_end}, amp={'ON' if amp_enable else 'OFF'}")
print(f"Looking for: 'TMCC NOT OK' = weak signal, parameters printed = strong signal")
print()

for ch in range(ch_start, ch_end + 1):
    freq = 473.143e6 + (ch - 13) * 6e6
    tb = gr.top_block()
    src = osmosdr.source(args="numchan=1 hackrf=0")
    src.set_sample_rate(SAMP_RATE)
    src.set_center_freq(freq)
    if amp_enable:
        src.set_gain(14, 'RF', 0)
    src.set_gain(40, 'IF', 0)
    src.set_gain(62, 'BB', 0)

    lpf = gr_filter.fir_filter_ccf(1,
        gr_filter.firdes.low_pass(1, SAMP_RATE, 5.8e6 / 2.0, 0.5e6,
                                  window.WIN_HAMMING, 6.76))
    ofdm = isdbt.ofdm_synchronization(MODE, 1.0 / 16, False)
    tmcc = isdbt.tmcc_decoder(MODE, True)
    null_out = blocks.null_sink(gr.sizeof_gr_complex * 13 * cps)

    tb.connect(src, lpf, ofdm, tmcc, null_out)
    tb.start()
    time.sleep(3)
    tb.stop()
    tb.wait()
    print(f"ch{ch:2d} ({freq / 1e6:.3f} MHz) done")
    sys.stdout.flush()
    time.sleep(0.3)
