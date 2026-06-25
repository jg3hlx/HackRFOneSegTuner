#!/usr/bin/env python3
"""ISDB-T transmitter — TS to IQ (complex float32) or HackRF output.

Usage:
  # One-seg only, output to IQ file
  python3 isdbt_tx.py --ts-a oneseg.ts -o tx_ch23.cf32

  # One-seg + full-seg (two TS inputs)
  python3 isdbt_tx.py --ts-a oneseg.ts --ts-b fullseg.ts -o tx_ch23.cf32

  # Live HackRF output
  python3 isdbt_tx.py --ts-a oneseg.ts 23 --amp --tx-gain 30
"""
import sys
import os
import argparse
import signal
import time

from gnuradio import gr, blocks, digital, dtv, fft
from gnuradio.fft import window
from gnuradio import isdbt

MODE = 3
CARRIERS_PER_SEG = 96 * 2 ** (MODE - 1)   # 384
DATA_CARRIERS = 13 * CARRIERS_PER_SEG      # 4992
TOTAL_CARRIERS = 2 ** (10 + MODE)          # 8192
SAMP_RATE = 8e6 * 64 / 63

SEG_A, CONST_A, RATE_A, LEN_A = 1, 4, 1, 4

MOD_MAP = {
    'qpsk':  (4,  dtv.MOD_QPSK,  dtv.C2_3, 1),
    '16qam': (16, dtv.MOD_16QAM, dtv.C3_4, 2),
    '64qam': (64, dtv.MOD_64QAM, dtv.C3_4, 2),
}

parser = argparse.ArgumentParser(description='ISDB-T Transmitter')
parser.add_argument('channel', type=int, nargs='?', default=None,
                    help='UHF channel (13-62) for live HackRF TX')
parser.add_argument('--ts-a', type=str, required=True,
                    help='Layer A (one-seg) TS input file')
parser.add_argument('--ts-b', type=str, default=None,
                    help='Layer B (full-seg) TS input file')
parser.add_argument('--mod-b', type=str, default='64qam',
                    choices=['qpsk', '16qam', '64qam'],
                    help='Layer B modulation (default: 64qam)')
parser.add_argument('--guard', type=str, default='1/8',
                    choices=['1/4', '1/8', '1/16', '1/32'])
parser.add_argument('--bb-gain', type=float, default=0.0022097087,
                    help='Baseband gain scaling')
parser.add_argument('--amp', action='store_true', help='Enable RF amp (HackRF)')
parser.add_argument('--tx-gain', type=int, default=30, help='TX IF gain (HackRF)')
parser.add_argument('--repeat', action='store_true',
                    help='Loop TS input (for continuous TX)')
parser.add_argument('-o', '--output', type=str, default=None,
                    help='Output IQ file (cf32). If omitted, uses HackRF.')
args = parser.parse_args()

CONST_B, DVB_MOD_B, DVB_RATE_B, RATE_B = MOD_MAP[args.mod_b]
SEG_B, LEN_B = 12, 2

guard_map = {'1/4': 0.25, '1/8': 0.125, '1/16': 1.0 / 16, '1/32': 1.0 / 32}
guard = guard_map[args.guard]
guard_samples = int(TOTAL_CARRIERS * guard)

live_mode = args.output is None
if live_mode and args.channel is None:
    parser.error('Specify UHF channel for live HackRF TX, or use -o for file output')

if live_mode:
    freq = 473.143e6 + (args.channel - 13) * 6e6

print("=== ISDB-T Transmitter ===")
print(f"Layer A: {args.ts_a} (QPSK 2/3, 1 seg)")
if args.ts_b:
    print(f"Layer B: {args.ts_b} ({args.mod_b.upper()} 12 seg)")
else:
    print(f"Layer B: null (zeros)")
print(f"Guard:   {args.guard} ({guard_samples} samples)")
if live_mode:
    print(f"Channel: {args.channel} ({freq / 1e6:.3f} MHz)")
    print(f"TX gain: {args.tx_gain}, AMP: {'ON' if args.amp else 'OFF'}")
else:
    print(f"Output:  {args.output}")
print()

tb = gr.top_block()

# --- Layer A (one-seg, QPSK, rate 2/3) ---
src_a = blocks.file_source(gr.sizeof_char, args.ts_a, args.repeat)
s2v_a = blocks.stream_to_vector(gr.sizeof_char, 188)
rs_enc_a = dtv.dvbt_reed_solomon_enc(2, 8, 0x11d, 255, 239, 8, 51, 1)
e_disp_a = isdbt.energy_dispersal(MODE, CONST_A, RATE_A, SEG_A)
b_intlv_a = isdbt.byte_interleaver(MODE, CONST_A, RATE_A, SEG_A)
inner_a = dtv.dvbt_inner_coder(1, 1512 * 4, dtv.MOD_QPSK, dtv.ALPHA4, dtv.C2_3)
v2s_a = blocks.vector_to_stream(gr.sizeof_char, 1512 * 4)
carrier_mod_a = isdbt.carrier_modulation(MODE, SEG_A, CONST_A)

tb.connect(src_a, s2v_a, rs_enc_a, e_disp_a, b_intlv_a, inner_a, v2s_a, carrier_mod_a)

# --- Layer B (full-seg, 64QAM, rate 3/4) or zeros ---
hier_comb = isdbt.hierarchical_combinator(MODE, SEG_A, SEG_B, 0)
tb.connect(carrier_mod_a, (hier_comb, 0))

if args.ts_b:
    src_b = blocks.file_source(gr.sizeof_char, args.ts_b, args.repeat)
    s2v_b = blocks.stream_to_vector(gr.sizeof_char, 188)
    rs_enc_b = dtv.dvbt_reed_solomon_enc(2, 8, 0x11d, 255, 239, 8, 51, 1)
    e_disp_b = isdbt.energy_dispersal(MODE, CONST_B, RATE_B, SEG_B)
    b_intlv_b = isdbt.byte_interleaver(MODE, CONST_B, RATE_B, SEG_B)
    inner_b = dtv.dvbt_inner_coder(1, 1512 * 4, DVB_MOD_B, dtv.ALPHA4, DVB_RATE_B)
    v2s_b = blocks.vector_to_stream(gr.sizeof_char, 1512 * 4)
    carrier_mod_b = isdbt.carrier_modulation(MODE, SEG_B, CONST_B)
    tb.connect(src_b, s2v_b, rs_enc_b, e_disp_b, b_intlv_b, inner_b, v2s_b, carrier_mod_b)
    tb.connect(carrier_mod_b, (hier_comb, 1))
else:
    one_vec = [0 + 0j] * (SEG_B * CARRIERS_PER_SEG)
    zero_b = blocks.vector_source_c(one_vec, True, SEG_B * CARRIERS_PER_SEG)
    if not args.repeat:
        head_b = blocks.head(gr.sizeof_gr_complex * SEG_B * CARRIERS_PER_SEG, 500000)
        tb.connect(zero_b, head_b)
        tb.connect(head_b, (hier_comb, 1))
    else:
        tb.connect(zero_b, (hier_comb, 1))

# --- OFDM frame construction ---
time_intlv = isdbt.time_interleaver(MODE, SEG_A, LEN_A, SEG_B, LEN_B, 0, 0)
freq_intlv = isdbt.frequency_interleaver(True, MODE)
skiphead = blocks.skiphead(gr.sizeof_gr_complex * DATA_CARRIERS, 2)
pilot = isdbt.pilot_signals(MODE)
tmcc_enc = isdbt.tmcc_encoder(MODE, True,
                              CONST_A, CONST_B, CONST_A,
                              RATE_A, RATE_B, 0,
                              LEN_A, LEN_B, 0,
                              SEG_A, SEG_B, 0)
ifft = fft.fft_vcc(TOTAL_CARRIERS, False,
                    window.rectangular(TOTAL_CARRIERS), True)
cp = digital.ofdm_cyclic_prefixer(TOTAL_CARRIERS,
                                   TOTAL_CARRIERS + guard_samples, 0, '')
gain_blk = blocks.multiply_const_cc(args.bb_gain)

tb.connect(hier_comb, time_intlv, freq_intlv, skiphead, pilot, tmcc_enc,
           ifft, cp, gain_blk)

# --- Output ---
if live_mode:
    import osmosdr
    sink = osmosdr.sink(args="numchan=1 hackrf=0")
    sink.set_sample_rate(SAMP_RATE)
    sink.set_center_freq(freq)
    if args.amp:
        sink.set_gain(14, 'RF', 0)
    sink.set_gain(args.tx_gain, 'IF', 0)
    tb.connect(gain_blk, sink)
else:
    sink = blocks.file_sink(gr.sizeof_gr_complex, args.output, False)
    tb.connect(gain_blk, sink)

running = True


def signal_handler(sig, frame):
    global running
    print("\nStopping...")
    running = False


signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

print("Starting transmitter...")
t0 = time.time()
tb.start()

try:
    while running:
        time.sleep(2)
        dt = time.time() - t0
        if not live_mode and args.output:
            sz = os.path.getsize(args.output) if os.path.exists(args.output) else 0
            print(f"\r  {dt:.0f}s  {sz / 1e6:.1f} MB    ", end='', flush=True)
            if not args.repeat and sz > 0:
                import threading
                done = threading.Event()

                def _wait():
                    tb.wait()
                    done.set()

                threading.Thread(target=_wait, daemon=True).start()
                if done.wait(timeout=max(0, dt * 0.5)):
                    break
        else:
            print(f"\r  {dt:.0f}s TX active    ", end='', flush=True)
except KeyboardInterrupt:
    pass

tb.stop()
tb.wait()

dt = time.time() - t0
print(f"\n\nDone in {dt:.1f}s")
if not live_mode and args.output and os.path.exists(args.output):
    sz = os.path.getsize(args.output)
    duration = sz / (SAMP_RATE * 8)
    print(f"  {args.output}: {sz / 1e6:.1f} MB ({duration:.2f}s of IQ)")
