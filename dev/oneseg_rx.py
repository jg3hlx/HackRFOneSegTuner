#!/usr/bin/env python3
"""
ISDB-T receiver for HackRF One using GNURadio + gr-isdbt.

Outputs:
  Layer A (One-Seg, 1 seg, QPSK)    -> /tmp/oneseg_a.ts  (FIFO -> ffplay)
  Layer B (Full-Seg, 12 seg, 64QAM) -> /tmp/oneseg_b.ts  (regular file)

Based on gr-isdbt rx_demo.grc.
"""

import argparse
import os
import signal
import stat
import subprocess
import sys
import time

from gnuradio import gr, blocks
from gnuradio import filter as gr_filter
from gnuradio.filter import firdes
from gnuradio.fft import window
from gnuradio import isdbt
import osmosdr


MODE = 3
SAMP_RATE = 8e6 * 64 / 63  # ~8.126984 MHz


def channel_to_freq(ch):
    """ISDB-T UHF channel number (13-62) -> center frequency in Hz."""
    return int(ch * 6e6 + 395e6 + 1e6 / 7)


def ensure_fifo(path):
    if os.path.exists(path):
        if stat.S_ISFIFO(os.stat(path).st_mode):
            return
        os.remove(path)
    os.mkfifo(path)


class ISDBTReceiver(gr.top_block):
    def __init__(self, center_freq, rf_gain, if_gain, bb_gain,
                 output_a, output_b):
        gr.top_block.__init__(self, "ISDB-T Receiver")

        # ── HackRF via osmosdr ──
        self.src = osmosdr.source(args="numchan=1 hackrf=0")
        self.src.set_sample_rate(SAMP_RATE)
        self.src.set_center_freq(center_freq, 0)
        self.src.set_freq_corr(0, 0)
        self.src.set_dc_offset_mode(0, 0)
        self.src.set_iq_balance_mode(0, 0)
        self.src.set_gain_mode(False, 0)
        self.src.set_gain(rf_gain, 0)
        self.src.set_if_gain(if_gain, 0)
        self.src.set_bb_gain(bb_gain, 0)

        # ── Low-pass filter ──
        taps = firdes.low_pass(
            1, SAMP_RATE, 5.8e6 / 2.0, 0.5e6, window.WIN_HAMMING, 6.76)
        self.lpf = gr_filter.fir_filter_ccf(1, taps)

        # ── ISDB-T OFDM demodulation ──
        self.ofdm_sync = isdbt.ofdm_synchronization(MODE, 1.0 / 16, False)
        self.tmcc_dec = isdbt.tmcc_decoder(MODE, True)
        self.freq_deint = isdbt.frequency_deinterleaver(True, MODE)
        self.time_deint = isdbt.time_deinterleaver(
            MODE,
            1, 4,   # segments_A, length_A
            12, 2,  # segments_B, length_B
            0, 0,   # segments_C, length_C
        )
        self.sym_demap = isdbt.symbol_demapper(
            MODE,
            1, 4,    # segments_A, QPSK
            12, 64,  # segments_B, 64QAM
            0, 64,   # segments_C (unused)
        )

        # ── Layer A chain (One-Seg: 1 segment, QPSK, rate=2) ──
        self.bit_deint_a = isdbt.bit_deinterleaver(MODE, 1, 4)
        self.viterbi_a = isdbt.viterbi_decoder(4, 2)
        self.byte_deint_a = isdbt.byte_deinterleaver()
        self.energy_desc_a = isdbt.energy_descrambler()
        self.rs_dec_a = isdbt.reed_solomon_dec_isdbt()
        self.v2s_a = blocks.vector_to_stream(gr.sizeof_char, 188)
        self.sink_a = blocks.file_sink(gr.sizeof_char, output_a, False)
        self.sink_a.set_unbuffered(True)

        # ── Layer B chain (Full-Seg: 12 segments, 64QAM, rate=2) ──
        self.bit_deint_b = isdbt.bit_deinterleaver(MODE, 12, 64)
        self.viterbi_b = isdbt.viterbi_decoder(64, 2)
        self.byte_deint_b = isdbt.byte_deinterleaver()
        self.energy_desc_b = isdbt.energy_descrambler()
        self.rs_dec_b = isdbt.reed_solomon_dec_isdbt()
        self.v2s_b = blocks.vector_to_stream(gr.sizeof_char, 188)
        self.sink_b = blocks.file_sink(gr.sizeof_char, output_b, False)
        self.sink_b.set_unbuffered(False)

        # Null sinks for optional BER output ports
        self.null_ber_vit_a = blocks.null_sink(gr.sizeof_float)
        self.null_ber_vit_b = blocks.null_sink(gr.sizeof_float)
        self.null_ber_rs_a = blocks.null_sink(gr.sizeof_float)
        self.null_ber_rs_b = blocks.null_sink(gr.sizeof_float)

        # ── Connections ──
        # Common path
        self.connect(
            self.src, self.lpf, self.ofdm_sync, self.tmcc_dec,
            self.freq_deint, self.time_deint, self.sym_demap)

        # Layer A (demapper port 0)
        self.connect(
            (self.sym_demap, 0),
            self.bit_deint_a, self.viterbi_a,
            self.byte_deint_a, self.energy_desc_a,
            self.rs_dec_a, self.v2s_a, self.sink_a)
        self.connect((self.viterbi_a, 1), self.null_ber_vit_a)
        self.connect((self.rs_dec_a, 1), self.null_ber_rs_a)

        # Layer B (demapper port 1)
        self.connect(
            (self.sym_demap, 1),
            self.bit_deint_b, self.viterbi_b,
            self.byte_deint_b, self.energy_desc_b,
            self.rs_dec_b, self.v2s_b, self.sink_b)
        self.connect((self.viterbi_b, 1), self.null_ber_vit_b)
        self.connect((self.rs_dec_b, 1), self.null_ber_rs_b)


def main():
    parser = argparse.ArgumentParser(
        description="ISDB-T One-Seg / Full-Seg receiver (HackRF One)")
    freq_group = parser.add_mutually_exclusive_group()
    freq_group.add_argument(
        "--freq", type=int, default=None,
        help="Center frequency in Hz (default: ch13 = 473143000)")
    freq_group.add_argument(
        "--channel", type=int, default=None,
        help="ISDB-T UHF channel number 13-62")
    parser.add_argument("--gain", type=float, default=40,
                        help="RF gain in dB (default: 40)")
    parser.add_argument("--if-gain", type=float, default=20,
                        help="IF gain in dB (default: 20)")
    parser.add_argument("--bb-gain", type=float, default=20,
                        help="BB gain in dB (default: 20)")
    parser.add_argument("--no-play", action="store_true",
                        help="Don't launch ffplay (write to regular files)")
    args = parser.parse_args()

    if args.channel is not None:
        if not 13 <= args.channel <= 62:
            parser.error(f"channel must be 13-62, got {args.channel}")
        center_freq = channel_to_freq(args.channel)
    elif args.freq is not None:
        center_freq = args.freq
    else:
        center_freq = channel_to_freq(13)

    ch_approx = round((center_freq - 473.143e6) / 6e6) + 13

    ts_a = "/tmp/oneseg_a.ts"
    ts_b = "/tmp/oneseg_b.ts"

    print(f"Channel   : ~{ch_approx}")
    print(f"Frequency : {center_freq / 1e6:.3f} MHz")
    print(f"Gain      : RF={args.gain} IF={args.if_gain} BB={args.bb_gain}")

    child_procs = []

    if args.no_play:
        for p in (ts_a, ts_b):
            if os.path.exists(p):
                os.remove(p)
        print(f"Layer A   : {ts_a}  (file)")
        print(f"Layer B   : {ts_b}  (file)")
    else:
        # Layer A: FIFO for live playback via ffplay
        ensure_fifo(ts_a)
        # Layer B: regular file (avoids FIFO stall when no reader)
        if os.path.exists(ts_b):
            os.remove(ts_b)

        print(f"Layer A   : {ts_a}  (FIFO -> ffplay)")
        print(f"Layer B   : {ts_b}  (file, play with: ffplay {ts_b})")

        # Start ffplay — it blocks on open() until the flowgraph opens
        # the FIFO for writing, so launch in a subprocess first.
        ffplay = subprocess.Popen(
            ["ffplay", "-i", ts_a,
             "-fflags", "nobuffer+discardcorrupt",
             "-analyzeduration", "2000000",
             "-probesize", "1000000",
             "-framedrop",
             "-window_title", "ISDB-T One-Seg"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL)
        child_procs.append(ffplay)
        print(f"ffplay    : PID {ffplay.pid}")

        # Let ffplay call open() on the FIFO before the flowgraph does.
        time.sleep(0.5)

    tb = ISDBTReceiver(center_freq, args.gain, args.if_gain, args.bb_gain,
                       ts_a, ts_b)

    def shutdown(sig=None, frame=None):
        print("\nStopping...")
        tb.stop()
        tb.wait()
        for p in child_procs:
            p.terminate()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    print("Starting ISDB-T receiver... (Ctrl+C to stop)")
    tb.start()

    try:
        tb.wait()
    except KeyboardInterrupt:
        pass
    finally:
        tb.stop()
        tb.wait()
        for p in child_procs:
            p.terminate()


if __name__ == "__main__":
    main()
