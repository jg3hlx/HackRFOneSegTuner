#!/usr/bin/env python3
"""Try different guard intervals on a specific channel."""
import sys, time
from gnuradio import gr, blocks, filter as gr_filter
from gnuradio.fft import window
from gnuradio import isdbt
import osmosdr

MODE = 3
SAMP_RATE = 8e6 * 64 / 63
cps = 96 * 2**(MODE - 1)
ch = int(sys.argv[1]) if len(sys.argv) > 1 else 32
freq = 473.143e6 + (ch - 13) * 6e6

for guard_denom in [4, 8, 16, 32]:
    guard = 1.0 / guard_denom
    print(f"\n=== ch{ch} guard=1/{guard_denom} ===")
    sys.stdout.flush()

    tb = gr.top_block()
    src = osmosdr.source(args="numchan=1 hackrf=0")
    src.set_sample_rate(SAMP_RATE)
    src.set_center_freq(freq)
    src.set_gain(14, 'RF', 0)
    src.set_gain(40, 'IF', 0)
    src.set_gain(40, 'BB', 0)

    lpf = gr_filter.fir_filter_ccf(1,
        gr_filter.firdes.low_pass(1, SAMP_RATE, 5.8e6 / 2.0, 0.5e6,
                                  window.WIN_HAMMING, 6.76))
    ofdm = isdbt.ofdm_synchronization(MODE, guard, False)
    tmcc = isdbt.tmcc_decoder(MODE, True)
    null_out = blocks.null_sink(gr.sizeof_gr_complex * 13 * cps)

    tb.connect(src, lpf, ofdm, tmcc, null_out)
    tb.start()
    time.sleep(8)
    tb.stop()
    tb.wait()
    print(f"guard=1/{guard_denom} done")
    sys.stdout.flush()
    time.sleep(0.3)
