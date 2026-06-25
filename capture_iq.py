#!/usr/bin/env python3
"""Capture raw IQ data from HackRF for offline analysis."""
import sys, time, os, argparse, tempfile
from gnuradio import gr, blocks
import osmosdr

SAMP_RATE = 8e6 * 64 / 63

parser = argparse.ArgumentParser(description='HackRF IQ Capture')
parser.add_argument('channel', type=int, help='UHF channel (13-62)')
parser.add_argument('--duration', type=int, default=10, help='Seconds to capture')
parser.add_argument('--amp', action='store_true', help='Enable RF amp')
parser.add_argument('--if-gain', type=int, default=24)
parser.add_argument('--bb-gain', type=int, default=24)
parser.add_argument('--auto-gain', action='store_true',
                    help='Auto-calibrate gain to avoid clipping')
parser.add_argument('-o', '--output', type=str, default=None)
args = parser.parse_args()

freq = 473.143e6 + (args.channel - 13) * 6e6

if args.auto_gain:
    import numpy as np
    print("=== Auto Gain Calibration ===")
    candidates = [(8, 16), (16, 16), (24, 24), (32, 32), (40, 40)]
    best_if, best_bb = 24, 24
    best_score = -999
    for if_g, bb_g in candidates:
        tmpiq = tempfile.mktemp(suffix='.cf32')
        cal_tb = gr.top_block()
        cal_src = osmosdr.source(args="numchan=1 hackrf=0")
        cal_src.set_sample_rate(SAMP_RATE)
        cal_src.set_center_freq(freq)
        if args.amp:
            cal_src.set_gain(14, 'RF', 0)
        cal_src.set_gain(if_g, 'IF', 0)
        cal_src.set_gain(bb_g, 'BB', 0)
        cal_head = blocks.head(gr.sizeof_gr_complex, int(SAMP_RATE * 1))
        cal_sink = blocks.file_sink(gr.sizeof_gr_complex, tmpiq, False)
        cal_tb.connect(cal_src, cal_head, cal_sink)
        cal_tb.start()
        cal_tb.wait()
        d = np.fromfile(tmpiq, dtype=np.complex64)
        pwr = float(np.mean(np.abs(d) ** 2))
        peak = float(np.max(np.abs(d)))
        pwr_db = 10 * np.log10(pwr) if pwr > 0 else -99
        os.remove(tmpiq)
        clipping = peak > 0.9
        score = pwr_db if not clipping else pwr_db - 100
        print(f"  IF={if_g:2d} BB={bb_g:2d}: {pwr_db:+.1f} dB peak={peak:.3f}{'  CLIP!' if clipping else ''}")
        if score > best_score:
            best_score = score
            best_if, best_bb = if_g, bb_g
    args.if_gain, args.bb_gain = best_if, best_bb
    print(f"  → IF={best_if} BB={best_bb}")

outfile = args.output or f"ch{args.channel}_{freq/1e6:.0f}MHz.cf32"

print(f"Capturing ch{args.channel} ({freq/1e6:.3f} MHz) for {args.duration}s → {outfile}")
print(f"  Sample rate: {SAMP_RATE/1e6:.3f} MHz, Gain: IF={args.if_gain} BB={args.bb_gain}")
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
