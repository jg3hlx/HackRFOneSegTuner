#!/usr/bin/env python3
"""Offline ISDB-T tester v2 - with message port connections and freq sweep."""
import sys, time, os, argparse
from gnuradio import gr, blocks, filter as gr_filter, analog
from gnuradio.fft import window
from gnuradio import isdbt
import pmt

MODE = 3
SAMP_RATE = 8e6 * 64 / 63
cps = 96 * 2**(MODE - 1)

parser = argparse.ArgumentParser(description='Offline ISDB-T tester v2')
parser.add_argument('iqfile', help='Input IQ file (complex float32)')
parser.add_argument('--guard', type=str, default='1/16',
                    choices=['1/4', '1/8', '1/16', '1/32'])
parser.add_argument('--freq-offset', type=float, default=0,
                    help='Frequency offset correction in Hz')
parser.add_argument('--sweep', action='store_true',
                    help='Sweep freq offsets from -50kHz to +50kHz')
parser.add_argument('--full-chain', action='store_true')
parser.add_argument('-o', '--output', type=str, default='/tmp/oneseg_a.ts')
parser.add_argument('--play', action='store_true')
args = parser.parse_args()

guard_map = {'1/4': 0.25, '1/8': 0.125, '1/16': 1.0/16, '1/32': 1.0/32}
guard = guard_map[args.guard]

def run_test(iqfile, freq_offset, guard, full_chain=False, output='/tmp/oneseg_a.ts', play=False):
    tb = gr.top_block()
    src = blocks.file_source(gr.sizeof_gr_complex, iqfile, False)

    last = src
    if freq_offset != 0:
        rotator = analog.sig_source_c(SAMP_RATE, analog.GR_COS_WAVE, freq_offset, 1, 0)
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

    tb.connect(last, lpf, ofdm, tmcc)

    # Don't connect TMCC reset → OFDM - let OFDM sync stabilize on its own
    # tb.msg_connect(tmcc, "ofdm reset", ofdm, "reset")

    if not full_chain:
        null_out = blocks.null_sink(gr.sizeof_gr_complex * 13 * cps)
        tb.connect(tmcc, null_out)
    else:
        # One-seg: Layer A = QPSK, rate 2/3, 1 segment, time_interleave=4(mode3)
        # Full-seg: Layer B = 64QAM, rate 3/4, 12 segments, time_interleave=2(mode3)
        freq_di = isdbt.frequency_deinterleaver(True, MODE)
        time_di = isdbt.time_deinterleaver(MODE, 1, 4, 12, 2, 0, 0)
        sym_dm = isdbt.symbol_demapper(MODE, 1, 4, 12, 64, 0, 64)
        # Layer A: layer=0, segments=1, constellation=QPSK(4)
        bit_di = isdbt.bit_deinterleaver(MODE, 0, 1, 4)
        # Layer A: layer=0, constellation=QPSK(4), rate=2/3(1)
        viterbi_dec = isdbt.viterbi_decoder(0, 4, 1)
        byte_di = isdbt.byte_deinterleaver()
        energy = isdbt.energy_descrambler()
        rs = isdbt.reed_solomon_dec_isdbt()
        v2s = blocks.vector_to_stream(gr.sizeof_char, 188)

        if os.path.exists(output) and not play:
            os.remove(output)
        if play:
            os.mkfifo(output)
            import subprocess
            subprocess.Popen(['ffplay', '-i', output, '-autoexit'],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        sink = blocks.file_sink(gr.sizeof_char, output, False)
        null_b = blocks.null_sink(gr.sizeof_char * 13 * cps)
        null_ber = blocks.null_sink(gr.sizeof_float)
        null_rs = blocks.null_sink(gr.sizeof_float)

        tb.connect(tmcc, freq_di, time_di, sym_dm)
        tb.connect((sym_dm, 0), bit_di, viterbi_dec, byte_di, energy, rs, v2s, sink)
        tb.connect((sym_dm, 1), null_b)
        tb.connect((viterbi_dec, 1), null_ber)
        tb.connect((rs, 1), null_rs)

    t0 = time.time()
    tb.start()
    tb.wait()
    dt = time.time() - t0
    return dt

if args.sweep:
    import subprocess, re
    offsets = list(range(-50000, 50001, 5000))
    print(f"Sweeping {len(offsets)} offsets on {args.iqfile}")
    print(f"{'Offset':>8} | {'TMCC_OK':>8} {'NOT_OK':>8} {'WHAT':>6} {'Time':>5}")
    print("-" * 50)
    for off in offsets:
        cmd = ['python3', __file__, args.iqfile, '--guard', args.guard, '--freq-offset', str(off)]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        combined = proc.stdout + proc.stderr
        tmcc_ok = combined.count('TMCC OK')
        tmcc_not = combined.count('TMCC NOT OK')
        tmcc_what = combined.count('TMCC WHAT')
        has_params = 'TMCC ANALYSIS' in combined or 'Mod scheme' in combined
        marker = " <<< LOCK!" if tmcc_ok > 0 else ""
        print(f"{off:+8d} | {tmcc_ok:>8} {tmcc_not:>8} {tmcc_what:>6}   {marker}")
        sys.stdout.flush()
else:
    print(f"Offline test v2: {args.iqfile}")
    print(f"  Guard: {args.guard}, Freq offset: {args.freq_offset} Hz")
    dt = run_test(args.iqfile, args.freq_offset, guard, args.full_chain, args.output, args.play)
    sz_in = os.path.getsize(args.iqfile)
    duration = sz_in / 8 / SAMP_RATE
    print(f"\nProcessed {duration:.1f}s in {dt:.1f}s ({duration/dt:.1f}x)")
