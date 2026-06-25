#!/usr/bin/env python3
"""Full-seg ISDB-T receiver — captures Layer A (one-seg) + Layer B (full-seg) TS.

Usage:
  # Live capture from HackRF
  python3 fullseg_rx.py 23 --duration 30 -o fullseg_ch23.ts

  # Offline from IQ file
  python3 fullseg_rx.py --iq ch23_long.cf32 --freq-offset -10913 -o fullseg.ts

  # Layer A only (one-seg, same as before)
  python3 fullseg_rx.py 23 --layer a -o oneseg.ts

  # Layer B only (full-seg encrypted)
  python3 fullseg_rx.py 23 --layer b -o fullseg.ts
"""
import sys, os, argparse, signal, time, tempfile, subprocess, threading
from gnuradio import gr, blocks, filter as gr_filter, analog
from gnuradio.fft import window
from gnuradio import isdbt
import osmosdr

MODE = 3
SAMP_RATE = 8e6 * 64 / 63
cps = 96 * 2**(MODE - 1)   # 384 data carriers per segment
SUBCARRIER_HZ = SAMP_RATE / 8192

parser = argparse.ArgumentParser(description='Full-seg ISDB-T TS capture')
parser.add_argument('channel', type=int, nargs='?', default=None,
                    help='UHF channel (13-62) for live HackRF capture')
parser.add_argument('--iq', type=str, default=None,
                    help='Offline: input IQ file (complex float32)')
parser.add_argument('--freq-offset', type=float, default=0,
                    help='Frequency offset correction in Hz (offline mode)')
parser.add_argument('--guard', type=str, default='1/8',
                    choices=['1/4', '1/8', '1/16', '1/32'])
parser.add_argument('--ppm', type=float, default=20)
parser.add_argument('--sc', type=int, default=None,
                    help='Override subcarrier offset (live mode)')
parser.add_argument('--calibrate', action='store_true')
parser.add_argument('--amp', action='store_true', default=True)
parser.add_argument('--no-amp', action='store_true')
parser.add_argument('--if-gain', type=int, default=24)
parser.add_argument('--bb-gain', type=int, default=24)
parser.add_argument('--auto-gain', action='store_true',
                    help='Auto-calibrate gain (1s capture, pick best)')
parser.add_argument('--duration', type=int, default=None,
                    help='Capture duration in seconds (live mode)')
parser.add_argument('--layer', type=str, default='ab',
                    help='Which layers to output: a, b, or ab (default: ab)')
parser.add_argument('-o', '--output', type=str, default='fullseg.ts',
                    help='Output TS file (default: fullseg.ts)')
args = parser.parse_args()

if args.no_amp:
    args.amp = False

if args.channel is None and args.iq is None:
    parser.error('Specify channel for live capture or --iq for offline mode')

guard_map = {'1/4': 0.25, '1/8': 0.125, '1/16': 1.0/16, '1/32': 1.0/32}
guard = guard_map[args.guard]

live_mode = args.iq is None

if live_mode:
    freq = 473.143e6 + (args.channel - 13) * 6e6

    def calibrate_gain(freq, amp):
        """Capture 1s at various gain levels, pick one with good signal without clipping."""
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
            if amp:
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
        print(f"  → IF={best_if} BB={best_bb}")
        return best_if, best_bb

    if args.auto_gain:
        args.if_gain, args.bb_gain = calibrate_gain(freq, args.amp)

    def calibrate_offset(freq, amp, if_gain, bb_gain):
        print("=== Auto Calibration ===")
        tmpiq = tempfile.mktemp(suffix='.cf32')
        print(f"Capturing 5s from {freq/1e6:.3f} MHz...")
        cal_tb = gr.top_block()
        cal_src = osmosdr.source(args="numchan=1 hackrf=0")
        cal_src.set_sample_rate(SAMP_RATE)
        cal_src.set_center_freq(freq)
        if amp:
            cal_src.set_gain(14, 'RF', 0)
        cal_src.set_gain(if_gain, 'IF', 0)
        cal_src.set_gain(bb_gain, 'BB', 0)
        cal_head = blocks.head(gr.sizeof_gr_complex, int(SAMP_RATE * 5))
        cal_sink = blocks.file_sink(gr.sizeof_gr_complex, tmpiq, False)
        cal_tb.connect(cal_src, cal_head, cal_sink)
        cal_tb.start()
        cal_tb.wait()

        best_sc, best_sz = 0, 0
        nominal = round(20 * 1e-6 * freq / SUBCARRIER_HZ)
        for n_sc in range(nominal - 2, nominal + 3):
            corr = -(n_sc * SUBCARRIER_HZ)
            outts = tempfile.mktemp(suffix='.ts')
            cmd = ['python3', os.path.join(os.path.dirname(__file__), 'offline_test2.py'),
                   tmpiq, '--guard', args.guard, '--full-chain',
                   '--freq-offset', str(corr), '-o', outts]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            sz = os.path.getsize(outts) if os.path.exists(outts) else 0
            print(f"  offset {n_sc:+3d}sc ({corr:+.0f} Hz): {sz/1024:.1f} KB")
            if sz > best_sz:
                best_sz = sz
                best_sc = n_sc
            if os.path.exists(outts):
                os.remove(outts)
        os.remove(tmpiq)
        if best_sz == 0:
            print("WARNING: No offset produced TS. Using nominal.")
            return nominal
        print(f"Best: {best_sc:+d} subcarriers ({best_sz/1024:.1f} KB)")
        return best_sc

    if args.calibrate:
        n_subcarriers = calibrate_offset(freq, args.amp, args.if_gain, args.bb_gain)
    elif args.sc is not None:
        n_subcarriers = args.sc
    else:
        offset_hz = args.ppm * 1e-6 * freq
        n_subcarriers = round(offset_hz / SUBCARRIER_HZ)

    correction_hz = -(n_subcarriers * SUBCARRIER_HZ)
else:
    correction_hz = args.freq_offset

layers = args.layer.lower()

print(f"=== Full-seg ISDB-T Receiver ===")
if live_mode:
    print(f"Channel:    {args.channel} ({freq/1e6:.3f} MHz)")
    print(f"Correction: {correction_hz:.0f} Hz ({n_subcarriers:+d} subcarriers)")
    print(f"Gain:       AMP={'ON' if args.amp else 'OFF'} IF={args.if_gain} BB={args.bb_gain}")
else:
    print(f"IQ file:    {args.iq}")
    print(f"Correction: {correction_hz:.0f} Hz")
print(f"Layers:     {layers.upper()}")
print(f"Output:     {args.output}")
print()

tb = gr.top_block()

if live_mode:
    src = osmosdr.source(args="numchan=1 hackrf=0")
    src.set_sample_rate(SAMP_RATE)
    src.set_center_freq(freq)
    if args.amp:
        src.set_gain(14, 'RF', 0)
    src.set_gain(args.if_gain, 'IF', 0)
    src.set_gain(args.bb_gain, 'BB', 0)
    rf_src = src
    if args.duration:
        head = blocks.head(gr.sizeof_gr_complex, int(SAMP_RATE * args.duration))
        tb.connect(src, head)
        rf_src = head
else:
    rf_src = blocks.file_source(gr.sizeof_gr_complex, args.iq, False)

last = rf_src
if correction_hz != 0:
    rotator = analog.sig_source_c(SAMP_RATE, analog.GR_COS_WAVE, correction_hz, 1, 0)
    mixer = blocks.multiply_cc()
    tb.connect(last, (mixer, 0))
    tb.connect(rotator, (mixer, 1))
    last = mixer

lpf = gr_filter.fir_filter_ccf(1,
    gr_filter.firdes.low_pass(1, SAMP_RATE, 5.8e6 / 2.0, 0.5e6,
                              window.WIN_HAMMING, 6.76))
lpf.set_min_output_buffer(524288)

ofdm = isdbt.ofdm_synchronization(MODE, guard, False)
tmcc = isdbt.tmcc_decoder(MODE, True)

freq_di = isdbt.frequency_deinterleaver(True, MODE)
time_di = isdbt.time_deinterleaver(MODE, 1, 4, 12, 2, 0, 0)
sym_dm = isdbt.symbol_demapper(MODE, 1, 4, 12, 64, 0, 64)

tb.connect(last, lpf, ofdm, tmcc, freq_di, time_di, sym_dm)

output_base = args.output
if output_base.endswith('.ts'):
    output_base = output_base[:-3]

if 'a' in layers:
    out_a = output_base + '_a.ts' if 'b' in layers else args.output
    bit_di_a = isdbt.bit_deinterleaver(MODE, 0, 1, 4)
    viterbi_a = isdbt.viterbi_decoder(0, 4, 1)      # layer 0, QPSK, rate 2/3
    byte_di_a = isdbt.byte_deinterleaver()
    energy_a = isdbt.energy_descrambler()
    rs_a = isdbt.reed_solomon_dec_isdbt()
    v2s_a = blocks.vector_to_stream(gr.sizeof_char, 188)
    sink_a = blocks.file_sink(gr.sizeof_char, out_a, False)
    null_ber_a = blocks.null_sink(gr.sizeof_float)
    null_rs_a = blocks.null_sink(gr.sizeof_float)

    tb.connect((sym_dm, 0), bit_di_a, viterbi_a, byte_di_a, energy_a, rs_a, v2s_a, sink_a)
    tb.connect((viterbi_a, 1), null_ber_a)
    tb.connect((rs_a, 1), null_rs_a)
    print(f"Layer A → {out_a}")
else:
    null_a = blocks.null_sink(gr.sizeof_char * 13 * cps)
    tb.connect((sym_dm, 0), null_a)

if 'b' in layers:
    out_b = output_base + '_b.ts' if 'a' in layers else args.output
    bit_di_b = isdbt.bit_deinterleaver(MODE, 1, 12, 64)
    bit_di_b.set_min_output_buffer(12 * cps * 4)
    viterbi_b = isdbt.viterbi_decoder(1, 64, 2)     # layer 1, 64QAM, rate 3/4
    byte_di_b = isdbt.byte_deinterleaver()
    energy_b = isdbt.energy_descrambler()
    rs_b = isdbt.reed_solomon_dec_isdbt()
    v2s_b = blocks.vector_to_stream(gr.sizeof_char, 188)
    sink_b = blocks.file_sink(gr.sizeof_char, out_b, False)
    null_ber_b = blocks.null_sink(gr.sizeof_float)
    null_rs_b = blocks.null_sink(gr.sizeof_float)

    tb.connect((sym_dm, 1), bit_di_b, viterbi_b, byte_di_b, energy_b, rs_b, v2s_b, sink_b)
    tb.connect((viterbi_b, 1), null_ber_b)
    tb.connect((rs_b, 1), null_rs_b)
    print(f"Layer B → {out_b}")
else:
    null_b = blocks.null_sink(gr.sizeof_char * 13 * cps)
    tb.connect((sym_dm, 1), null_b)

print()

running = True

def signal_handler(sig, frame):
    global running
    print("\nStopping...")
    running = False

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

print("Starting receiver... (Ctrl+C to stop)")
t0 = time.time()
tb.start()

fg_done = threading.Event()
if not live_mode:
    def _wait_fg():
        tb.wait()
        fg_done.set()
    threading.Thread(target=_wait_fg, daemon=True).start()

prev_total = -1
stall_count = 0
try:
    while running:
        if fg_done.wait(timeout=2):
            break
        dt = time.time() - t0
        sizes = []
        cur_total = 0
        if 'a' in layers:
            sz_a = os.path.getsize(out_a) if os.path.exists(out_a) else 0
            sizes.append(f"A:{sz_a/1024:.0f}KB")
            cur_total += sz_a
        if 'b' in layers:
            sz_b = os.path.getsize(out_b) if os.path.exists(out_b) else 0
            sizes.append(f"B:{sz_b/1024:.0f}KB")
            cur_total += sz_b
        print(f"\r  {dt:.0f}s  {' '.join(sizes)}    ", end='', flush=True)
except KeyboardInterrupt:
    pass

if not fg_done.is_set():
    tb.stop()
    tb.wait()

dt = time.time() - t0
print(f"\n\nDone in {dt:.1f}s")
if 'a' in layers and os.path.exists(out_a):
    sz = os.path.getsize(out_a)
    print(f"  Layer A: {out_a} ({sz/1024:.1f} KB, {sz/188:.0f} TS packets)")
if 'b' in layers and os.path.exists(out_b):
    sz = os.path.getsize(out_b)
    print(f"  Layer B: {out_b} ({sz/1024:.1f} KB, {sz/188:.0f} TS packets)")
