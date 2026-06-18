#!/usr/bin/env python3
"""Offline ISDB-T parameter tester. Replays captured IQ data with different settings."""
import sys, time, os, argparse
from gnuradio import gr, blocks, filter as gr_filter, analog
from gnuradio.fft import window
from gnuradio import isdbt

MODE = 3
SAMP_RATE = 8e6 * 64 / 63
cps = 96 * 2**(MODE - 1)

parser = argparse.ArgumentParser(description='Offline ISDB-T tester')
parser.add_argument('iqfile', help='Input IQ file (complex float32)')
parser.add_argument('--guard', type=str, default='1/16',
                    choices=['1/4', '1/8', '1/16', '1/32'],
                    help='Guard interval (default: 1/16)')
parser.add_argument('--freq-offset', type=float, default=0,
                    help='Apply frequency offset correction in Hz')
parser.add_argument('--full-chain', action='store_true',
                    help='Run full demod chain (not just TMCC check)')
parser.add_argument('-o', '--output', type=str, default='/tmp/oneseg_a.ts',
                    help='Output TS file')
parser.add_argument('--throttle', action='store_true',
                    help='Throttle to real-time (for ffplay)')
parser.add_argument('--play', action='store_true',
                    help='Launch ffplay')
args = parser.parse_args()

guard_map = {'1/4': 0.25, '1/8': 0.125, '1/16': 1.0/16, '1/32': 1.0/32}
guard = guard_map[args.guard]

print(f"Offline test: {args.iqfile}")
print(f"  Guard: {args.guard}, Freq offset: {args.freq_offset} Hz")
print(f"  Full chain: {args.full_chain}")

tb = gr.top_block()
src = blocks.file_source(gr.sizeof_gr_complex, args.iqfile, False)

if args.throttle or args.play:
    thr = blocks.throttle(gr.sizeof_gr_complex, SAMP_RATE, True)
    tb.connect(src, thr)
    last = thr
else:
    last = src

if args.freq_offset != 0:
    rotator = analog.sig_source_c(SAMP_RATE, analog.GR_COS_WAVE, args.freq_offset, 1, 0)
    mixer = blocks.multiply_cc()
    tb.connect(last, (mixer, 0))
    tb.connect(rotator, (mixer, 1))
    last = mixer

lpf = gr_filter.fir_filter_ccf(1,
    gr_filter.firdes.low_pass(1, SAMP_RATE, 5.8e6 / 2.0, 0.5e6,
                              window.WIN_HAMMING, 6.76))
ofdm = isdbt.ofdm_synchronization(MODE, guard, False)
tmcc = isdbt.tmcc_decoder(MODE, True)

lpf.set_min_output_buffer(65536)
tb.connect(last, lpf, ofdm, tmcc)

if not args.full_chain:
    null_out = blocks.null_sink(gr.sizeof_gr_complex * 13 * cps)
    tb.connect(tmcc, null_out)
else:
    freq_di = isdbt.frequency_deinterleaver(True, MODE)
    time_di = isdbt.time_deinterleaver(MODE, 1, 4, 12, 2, 0, 0)
    sym_dm = isdbt.symbol_demapper(MODE, 1, 4, 12, 64, 0, 64)
    bit_di = isdbt.bit_deinterleaver(MODE, 1, 4)
    viterbi = isdbt.viterbi_decoder(4, 2)
    byte_di = isdbt.byte_deinterleaver()
    energy = isdbt.energy_descrambler()
    rs = isdbt.reed_solomon_dec_isdbt()
    v2s = blocks.vector_to_stream(gr.sizeof_char, 188)

    if os.path.exists(args.output) and not args.play:
        os.remove(args.output)
    if args.play:
        os.mkfifo(args.output)
        import subprocess
        subprocess.Popen(['ffplay', '-i', args.output, '-autoexit'],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    sink = blocks.file_sink(gr.sizeof_char, args.output, False)
    null_b = blocks.null_sink(gr.sizeof_char * 12 * cps)
    null_ber = blocks.null_sink(gr.sizeof_float)
    null_rs = blocks.null_sink(gr.sizeof_float)

    tb.connect(tmcc, freq_di, time_di, sym_dm)
    tb.connect((sym_dm, 0), bit_di, viterbi, byte_di, energy, rs, v2s, sink)
    tb.connect((sym_dm, 1), null_b)
    tb.connect((viterbi, 1), null_ber)
    tb.connect((rs, 1), null_rs)

t0 = time.time()
tb.start()
tb.wait()
dt = time.time() - t0

sz_in = os.path.getsize(args.iqfile)
samples = sz_in // 8
duration = samples / SAMP_RATE
print(f"\nProcessed {duration:.1f}s of data in {dt:.1f}s ({duration/dt:.1f}x real-time)")

if args.full_chain and not args.play:
    sz_out = os.path.getsize(args.output) if os.path.exists(args.output) else 0
    print(f"Output: {sz_out} bytes in {args.output}")
