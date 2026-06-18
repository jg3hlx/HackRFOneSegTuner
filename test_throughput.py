#!/usr/bin/env python3
"""Test OFDM sync throughput with and without TMCC decoder."""
import sys, time
from gnuradio import gr, blocks, filter as gr_filter
from gnuradio.fft import window
from gnuradio import isdbt

MODE = 3
SAMP_RATE = 8e6 * 64 / 63
cps = 96 * 2**(MODE - 1)
active = 1 + 13 * 108 * 2**(MODE - 1)

iqfile = sys.argv[1] if len(sys.argv) > 1 else "ch16_optimal.cf32"

# Test 1: OFDM → null_sink (bypass TMCC)
tb = gr.top_block()
src = blocks.file_source(gr.sizeof_gr_complex, iqfile, False)
lpf = gr_filter.fir_filter_ccf(1,
    gr_filter.firdes.low_pass(1, SAMP_RATE, 5.8e6/2.0, 0.5e6, window.WIN_HAMMING, 6.76))
lpf.set_min_output_buffer(524288)
ofdm = isdbt.ofdm_synchronization(MODE, 0.125, False)
null_out = blocks.null_sink(gr.sizeof_gr_complex * active)
probe = blocks.probe_rate(gr.sizeof_gr_complex * active)

tb.connect(src, lpf, ofdm, null_out)
tb.connect(ofdm, probe)

t0 = time.time()
tb.start()
tb.wait()
dt = time.time() - t0
rate = probe.rate()
print(f"Without TMCC: {dt:.1f}s, output rate: {rate:.1f} vectors/sec")

# Test 2: With TMCC
tb2 = gr.top_block()
src2 = blocks.file_source(gr.sizeof_gr_complex, iqfile, False)
lpf2 = gr_filter.fir_filter_ccf(1,
    gr_filter.firdes.low_pass(1, SAMP_RATE, 5.8e6/2.0, 0.5e6, window.WIN_HAMMING, 6.76))
lpf2.set_min_output_buffer(524288)
ofdm2 = isdbt.ofdm_synchronization(MODE, 0.125, False)
tmcc2 = isdbt.tmcc_decoder(MODE, False)
null_out2 = blocks.null_sink(gr.sizeof_gr_complex * 13 * cps)

tb2.connect(src2, lpf2, ofdm2, tmcc2, null_out2)

t0 = time.time()
tb2.start()
tb2.wait()
dt2 = time.time() - t0
print(f"With TMCC:    {dt2:.1f}s")
