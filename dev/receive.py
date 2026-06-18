#!/usr/bin/env python3
"""ISDB-T One-Seg live receiver. Outputs MPEG-TS to /tmp/oneseg_a.ts"""
import sys, time, os, argparse
from gnuradio import gr, blocks, filter as gr_filter
from gnuradio.fft import window
from gnuradio import isdbt
import osmosdr

MODE = 3
SAMP_RATE = 8e6 * 64 / 63
cps = 96 * 2**(MODE - 1)

parser = argparse.ArgumentParser(description='ISDB-T One-Seg Receiver')
parser.add_argument('channel', type=int, nargs='?', default=27,
                    help='UHF channel number (13-62)')
parser.add_argument('--amp', action='store_true', help='Enable RF amp (+14dB)')
parser.add_argument('--if-gain', type=int, default=40, help='IF/LNA gain 0-40')
parser.add_argument('--bb-gain', type=int, default=40, help='BB/VGA gain 0-62')
parser.add_argument('--duration', type=int, default=30, help='Duration in seconds')
parser.add_argument('--play', action='store_true', help='Launch ffplay')
args = parser.parse_args()

freq = 473.143e6 + (args.channel - 13) * 6e6
print(f"ISDB-T One-Seg Receiver")
print(f"  Channel: {args.channel} ({freq / 1e6:.3f} MHz)")
print(f"  Gain: RF amp={'ON' if args.amp else 'OFF'}, IF={args.if_gain}, BB={args.bb_gain}")

tb = gr.top_block()

src = osmosdr.source(args="numchan=1 hackrf=0")
src.set_sample_rate(SAMP_RATE)
src.set_center_freq(freq)
if args.amp:
    src.set_gain(14, 'RF', 0)
src.set_gain(args.if_gain, 'IF', 0)
src.set_gain(args.bb_gain, 'BB', 0)

lpf = gr_filter.fir_filter_ccf(1,
    gr_filter.firdes.low_pass(1, SAMP_RATE, 5.8e6 / 2.0, 0.5e6,
                              window.WIN_HAMMING, 6.76))
ofdm = isdbt.ofdm_synchronization(MODE, 1.0 / 16, False)
tmcc = isdbt.tmcc_decoder(MODE, True)
freq_di = isdbt.frequency_deinterleaver(True, MODE)
time_di = isdbt.time_deinterleaver(MODE, 1, 4, 12, 2, 0, 0)
sym_dm = isdbt.symbol_demapper(MODE, 1, 4, 12, 64, 0, 64)

bit_di = isdbt.bit_deinterleaver(MODE, 1, 4)
viterbi = isdbt.viterbi_decoder(4, 2)
byte_di = isdbt.byte_deinterleaver()
energy = isdbt.energy_descrambler()
rs = isdbt.reed_solomon_dec_isdbt()
v2s = blocks.vector_to_stream(gr.sizeof_char, 188)

ts_path = '/tmp/oneseg_a.ts'
if os.path.exists(ts_path):
    os.remove(ts_path)

if args.play:
    os.mkfifo(ts_path)
    import subprocess
    ffplay = subprocess.Popen(['ffplay', '-i', ts_path, '-autoexit'],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

sink = blocks.file_sink(gr.sizeof_char, ts_path, False)

null_b = blocks.null_sink(gr.sizeof_char * 12 * cps)
null_ber = blocks.null_sink(gr.sizeof_float)
null_rs = blocks.null_sink(gr.sizeof_float)

tb.connect(src, lpf, ofdm, tmcc, freq_di, time_di, sym_dm)
tb.connect((sym_dm, 0), bit_di, viterbi, byte_di, energy, rs, v2s, sink)
tb.connect((sym_dm, 1), null_b)
tb.connect((viterbi, 1), null_ber)
tb.connect((rs, 1), null_rs)

print(f"\nStarting reception...")
sys.stdout.flush()
tb.start()

for i in range(args.duration):
    time.sleep(1)
    sz = os.path.getsize(ts_path) if os.path.exists(ts_path) and not args.play else 0
    status = f"output={sz}B" if not args.play else "FIFO mode"
    print(f"  t={i + 1}s {status}")
    sys.stdout.flush()

tb.stop()
tb.wait()
if not args.play:
    sz = os.path.getsize(ts_path) if os.path.exists(ts_path) else 0
    print(f"\nFinal: {sz} bytes in {ts_path}")
    if sz > 0:
        print("SUCCESS! Run: ffplay /tmp/oneseg_a.ts")
