#!/usr/bin/env python3
"""Live one-seg receiver with HackRF One → ffplay real-time display."""
import sys, os, argparse, signal, subprocess, time
from gnuradio import gr, blocks, filter as gr_filter, analog
from gnuradio.fft import window
from gnuradio import isdbt
import osmosdr

MODE = 3
SAMP_RATE = 8e6 * 64 / 63
cps = 96 * 2**(MODE - 1)
SUBCARRIER_HZ = SAMP_RATE / 8192

parser = argparse.ArgumentParser(description='Live one-seg receiver')
parser.add_argument('channel', type=int, help='UHF channel (13-62)')
parser.add_argument('--ppm', type=float, default=20,
                    help='Crystal error in PPM (default: 20 for HackRF)')
parser.add_argument('--amp', action='store_true', default=True,
                    help='Enable RF amp (default: on)')
parser.add_argument('--no-amp', action='store_true')
parser.add_argument('--if-gain', type=int, default=8)
parser.add_argument('--bb-gain', type=int, default=16)
parser.add_argument('--output', type=str, default=None,
                    help='Also save TS to file')
args = parser.parse_args()
if args.no_amp:
    args.amp = False

freq = 473.143e6 + (args.channel - 13) * 6e6

offset_hz = args.ppm * 1e-6 * freq
n_subcarriers = round(offset_hz / SUBCARRIER_HZ)
correction_hz = -(n_subcarriers * SUBCARRIER_HZ)

print(f"=== Live One-Seg Receiver ===")
print(f"Channel:    {args.channel} ({freq/1e6:.3f} MHz)")
print(f"PPM:        {args.ppm}")
print(f"Correction: {correction_hz:.0f} Hz ({n_subcarriers:+d} subcarriers)")
print(f"Gain:       AMP={'ON' if args.amp else 'OFF'} IF={args.if_gain} BB={args.bb_gain}")
print()

fifo_path = f"/tmp/oneseg_live_ch{args.channel}.ts"
if os.path.exists(fifo_path):
    os.remove(fifo_path)
os.mkfifo(fifo_path)

ffplay_proc = subprocess.Popen(
    ['ffplay', '-analyzeduration', '2000000', '-probesize', '500000',
     '-fflags', 'nobuffer', '-flags', 'low_delay',
     '-i', fifo_path,
     '-window_title', f'One-Seg ch{args.channel}'],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
)
print(f"ffplay started (PID {ffplay_proc.pid})")

tb = gr.top_block()

src = osmosdr.source(args="numchan=1 hackrf=0")
src.set_sample_rate(SAMP_RATE)
src.set_center_freq(freq)
if args.amp:
    src.set_gain(14, 'RF', 0)
src.set_gain(args.if_gain, 'IF', 0)
src.set_gain(args.bb_gain, 'BB', 0)

rotator = analog.sig_source_c(SAMP_RATE, analog.GR_COS_WAVE, correction_hz, 1, 0)
mixer = blocks.multiply_cc()
tb.connect(src, (mixer, 0))
tb.connect(rotator, (mixer, 1))

lpf = gr_filter.fir_filter_ccf(1,
    gr_filter.firdes.low_pass(1, SAMP_RATE, 5.8e6 / 2.0, 0.5e6,
                              window.WIN_HAMMING, 6.76))
lpf.set_min_output_buffer(524288)

ofdm = isdbt.ofdm_synchronization(MODE, 0.125, False)
tmcc = isdbt.tmcc_decoder(MODE, True)

freq_di = isdbt.frequency_deinterleaver(True, MODE)
time_di = isdbt.time_deinterleaver(MODE, 1, 4, 12, 2, 0, 0)
sym_dm = isdbt.symbol_demapper(MODE, 1, 4, 12, 64, 0, 64)
bit_di = isdbt.bit_deinterleaver(MODE, 0, 1, 4)
viterbi_dec = isdbt.viterbi_decoder(0, 4, 1)
byte_di = isdbt.byte_deinterleaver()
energy = isdbt.energy_descrambler()
rs = isdbt.reed_solomon_dec_isdbt()
v2s = blocks.vector_to_stream(gr.sizeof_char, 188)

sink = blocks.file_sink(gr.sizeof_char, fifo_path, False)
null_b = blocks.null_sink(gr.sizeof_char * 13 * cps)
null_ber = blocks.null_sink(gr.sizeof_float)
null_rs = blocks.null_sink(gr.sizeof_float)

tb.connect(mixer, lpf, ofdm, tmcc, freq_di, time_di, sym_dm)
tb.connect((sym_dm, 0), bit_di, viterbi_dec, byte_di, energy, rs, v2s, sink)
tb.connect((sym_dm, 1), null_b)
tb.connect((viterbi_dec, 1), null_ber)
tb.connect((rs, 1), null_rs)

if args.output:
    tee = blocks.tee(gr.sizeof_char, 2)
    file_sink = blocks.file_sink(gr.sizeof_char, args.output, False)
    tb.disconnect(v2s, sink)
    tb.connect(v2s, tee)
    tb.connect((tee, 0), sink)
    tb.connect((tee, 1), file_sink)

def signal_handler(sig, frame):
    print("\nStopping...")
    tb.stop()
    tb.wait()
    ffplay_proc.terminate()
    if os.path.exists(fifo_path):
        os.remove(fifo_path)
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

print("Starting receiver... (Ctrl+C to stop)")
tb.start()

try:
    while True:
        if ffplay_proc.poll() is not None:
            print("ffplay exited, stopping receiver...")
            break
        time.sleep(1)
except KeyboardInterrupt:
    pass

tb.stop()
tb.wait()
ffplay_proc.terminate()
if os.path.exists(fifo_path):
    os.remove(fifo_path)
print("Done.")
