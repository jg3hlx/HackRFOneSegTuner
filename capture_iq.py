#!/usr/bin/env python3
"""Capture raw IQ data from HackRF for offline analysis."""
import sys, time, os, argparse
from gnuradio import gr, blocks
import osmosdr

SAMP_RATE = 8e6 * 64 / 63

parser = argparse.ArgumentParser(description='HackRF IQ Capture')
parser.add_argument('channel', type=int, help='UHF channel (13-62)')
parser.add_argument('--duration', type=int, default=10, help='Seconds to capture')
parser.add_argument('--amp', action='store_true', help='Enable RF amp')
parser.add_argument('--if-gain', type=int, default=40)
parser.add_argument('--bb-gain', type=int, default=40)
parser.add_argument('-o', '--output', type=str, default=None)
args = parser.parse_args()

freq = 473.143e6 + (args.channel - 13) * 6e6
outfile = args.output or f"ch{args.channel}_{freq/1e6:.0f}MHz.cf32"

print(f"Capturing ch{args.channel} ({freq/1e6:.3f} MHz) for {args.duration}s → {outfile}")
print(f"  Sample rate: {SAMP_RATE/1e6:.3f} MHz, format: complex float32")
print(f"  Expected size: {SAMP_RATE * 8 * args.duration / 1e6:.0f} MB")

tb = gr.top_block()
src = osmosdr.source(args="numchan=1 hackrf=0")
src.set_sample_rate(SAMP_RATE)
src.set_center_freq(freq)
if args.amp:
    src.set_gain(14, 'RF', 0)
src.set_gain(args.if_gain, 'IF', 0)
src.set_gain(args.bb_gain, 'BB', 0)

head = blocks.head(gr.sizeof_gr_complex, int(SAMP_RATE * args.duration))
sink = blocks.file_sink(gr.sizeof_gr_complex, outfile, False)

tb.connect(src, head, sink)
tb.start()
tb.wait()

sz = os.path.getsize(outfile)
print(f"Done: {sz} bytes ({sz/1e6:.1f} MB), {sz/8/SAMP_RATE:.2f}s of data")
