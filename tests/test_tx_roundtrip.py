#!/usr/bin/env python3
"""Incremental TX→RX loopback tests for ISDB-T transmitter.

Layer 1: RS encode → RS decode
Layer 2: TX inner coding produces valid QPSK carriers
Layer 3: Full OFDM loopback (TX IQ → existing receiver → TS comparison)
"""
import os
import sys
import tempfile
import unittest

import numpy as np
from gnuradio import gr, blocks, digital, dtv, fft
from gnuradio.fft import window
from gnuradio import isdbt

sys.path.insert(0, os.path.dirname(__file__))

MODE = 3
CARRIERS_PER_SEG = 96 * 2 ** (MODE - 1)   # 384
DATA_CARRIERS = 13 * CARRIERS_PER_SEG      # 4992
TOTAL_CARRIERS = 2 ** (10 + MODE)          # 8192
SAMP_RATE = 8e6 * 64 / 63
GUARD = 1.0 / 8
GUARD_SAMPLES = int(TOTAL_CARRIERS * GUARD)  # 1024

SEG_A, CONST_A, RATE_A, LEN_A = 1, 4, 1, 4
SEG_B, CONST_B, RATE_B, LEN_B = 12, 64, 2, 2

N_TS_PACKETS = 2000


def make_zero_layer_b(tb, hier_comb, n_symbols):
    """Create a finite zero source for Layer B and connect to hier_comb port 1."""
    one_vec = [0 + 0j] * (SEG_B * CARRIERS_PER_SEG)
    zero_src = blocks.vector_source_c(one_vec, True, SEG_B * CARRIERS_PER_SEG)
    head = blocks.head(gr.sizeof_gr_complex * SEG_B * CARRIERS_PER_SEG, n_symbols)
    tb.connect(zero_src, head)
    tb.connect(head, (hier_comb, 1))


def make_test_ts(path, n_packets=N_TS_PACKETS):
    """Write a TS file with null packets carrying a known payload pattern."""
    with open(path, 'wb') as f:
        for i in range(n_packets):
            pkt = bytearray(188)
            pkt[0] = 0x47
            pkt[1] = 0x1F
            pkt[2] = 0xFF
            pkt[3] = 0x10 | (i & 0x0F)
            for j in range(4, 188):
                pkt[j] = (i + j) & 0xFF
            f.write(pkt)


def compare_ts_auto_align(path_in, path_out):
    """Compare TS files with automatic alignment detection.
    Tries multiple output starting positions to find the best contiguous match.
    Returns (matched, total, offset)."""
    with open(path_in, 'rb') as f:
        orig = f.read()
    with open(path_out, 'rb') as f:
        recv = f.read()

    n_orig = len(orig) // 188
    n_recv = len(recv) // 188
    if n_recv == 0:
        return 0, 0, -1

    best_matched, best_total, best_offset = 0, n_recv, -1
    for out_start in range(min(10, n_recv)):
        out_pkt = recv[out_start * 188:(out_start + 1) * 188]
        for j in range(min(n_orig, 300)):
            if orig[j * 188:(j + 1) * 188] == out_pkt:
                in_offset = j - out_start
                if in_offset < 0:
                    continue
                matched = 0
                total = min(n_orig - in_offset, n_recv)
                for i in range(total):
                    ip = orig[(in_offset + i) * 188:(in_offset + i + 1) * 188]
                    op = recv[i * 188:(i + 1) * 188]
                    if ip == op:
                        matched += 1
                if matched > best_matched:
                    best_matched = matched
                    best_total = total
                    best_offset = in_offset
                break
    return best_matched, best_total, best_offset


class TestRSRoundtrip(unittest.TestCase):
    """Layer 1: RS(204,188) encode then decode — verify TS packet recovery."""

    def test_rs_loopback(self):
        tmpdir = tempfile.mkdtemp(prefix='tx_rs_')
        ts_in = os.path.join(tmpdir, 'in.ts')
        ts_out = os.path.join(tmpdir, 'out.ts')
        make_test_ts(ts_in, 500)

        tb = gr.top_block()
        src = blocks.file_source(gr.sizeof_char, ts_in, False)
        s2v = blocks.stream_to_vector(gr.sizeof_char, 188)
        rs_enc = dtv.dvbt_reed_solomon_enc(2, 8, 0x11d, 255, 239, 8, 51, 1)
        rs_dec = isdbt.reed_solomon_dec_isdbt()
        v2s = blocks.vector_to_stream(gr.sizeof_char, 188)
        sink = blocks.file_sink(gr.sizeof_char, ts_out, False)
        null_rs = blocks.null_sink(gr.sizeof_float)

        tb.connect(src, s2v, rs_enc, rs_dec, v2s, sink)
        tb.connect((rs_dec, 1), null_rs)
        tb.run()

        self.assertTrue(os.path.exists(ts_out))
        sz = os.path.getsize(ts_out)
        self.assertGreater(sz, 0, "RS loopback produced no output")
        self.assertEqual(sz % 188, 0)

        matched, total, offset = compare_ts_auto_align(ts_in, ts_out)
        self.assertGreater(total, 0)
        self.assertEqual(matched, total,
                         f"RS loopback: {matched}/{total} matched, offset={offset}")


class TestCarrierQuality(unittest.TestCase):
    """Layer 2: Verify TX inner coding produces valid QPSK constellation."""

    def test_qpsk_constellation(self):
        tmpdir = tempfile.mkdtemp(prefix='tx_qpsk_')
        ts_in = os.path.join(tmpdir, 'in.ts')
        sym_file = os.path.join(tmpdir, 'symbols.bin')
        make_test_ts(ts_in)

        tb = gr.top_block()
        src = blocks.file_source(gr.sizeof_char, ts_in, False)
        s2v = blocks.stream_to_vector(gr.sizeof_char, 188)
        rs_enc = dtv.dvbt_reed_solomon_enc(2, 8, 0x11d, 255, 239, 8, 51, 1)
        e_disp = isdbt.energy_dispersal(MODE, CONST_A, RATE_A, SEG_A)
        b_intlv = isdbt.byte_interleaver(MODE, CONST_A, RATE_A, SEG_A)
        inner = dtv.dvbt_inner_coder(1, 1512 * 4, dtv.MOD_QPSK, dtv.ALPHA4, dtv.C2_3)
        v2s_inner = blocks.vector_to_stream(gr.sizeof_char, 1512 * 4)
        carrier_mod = isdbt.carrier_modulation(MODE, SEG_A, CONST_A)
        sink = blocks.file_sink(gr.sizeof_gr_complex * SEG_A * CARRIERS_PER_SEG,
                                sym_file, False)

        tb.connect(src, s2v, rs_enc, e_disp, b_intlv, inner, v2s_inner, carrier_mod, sink)
        tb.run()

        sz = os.path.getsize(sym_file) if os.path.exists(sym_file) else 0
        self.assertGreater(sz, 0, "No carrier output")

        data = np.fromfile(sym_file, dtype=np.complex64)
        n_symbols = len(data) // (SEG_A * CARRIERS_PER_SEG)
        self.assertGreater(n_symbols, 100, f"Only {n_symbols} OFDM symbols")

        # QPSK: all points should be near ±1/√2 ± j/√2
        ideal = 1.0 / np.sqrt(2)
        abs_re = np.abs(np.real(data))
        abs_im = np.abs(np.imag(data))
        re_ok = np.mean(np.abs(abs_re - ideal) < 0.1)
        im_ok = np.mean(np.abs(abs_im - ideal) < 0.1)
        self.assertGreater(re_ok, 0.90,
                           f"QPSK real component: {re_ok:.1%} near ±1/√2")
        self.assertGreater(im_ok, 0.90,
                           f"QPSK imag component: {im_ok:.1%} near ±1/√2")


class TestOFDMLoopback(unittest.TestCase):
    """Layer 3: Full OFDM loopback — TX produces IQ, existing receiver recovers TS."""

    def test_oneseg_iq_roundtrip(self):
        tmpdir = tempfile.mkdtemp(prefix='tx_ofdm_')
        ts_in = os.path.join(tmpdir, 'in.ts')
        iq_file = os.path.join(tmpdir, 'tx.cf32')
        ts_out = os.path.join(tmpdir, 'out.ts')
        make_test_ts(ts_in, 5000)

        tb = gr.top_block()

        src = blocks.file_source(gr.sizeof_char, ts_in, False)
        s2v = blocks.stream_to_vector(gr.sizeof_char, 188)
        rs_enc = dtv.dvbt_reed_solomon_enc(2, 8, 0x11d, 255, 239, 8, 51, 1)
        e_disp = isdbt.energy_dispersal(MODE, CONST_A, RATE_A, SEG_A)
        b_intlv = isdbt.byte_interleaver(MODE, CONST_A, RATE_A, SEG_A)
        inner = dtv.dvbt_inner_coder(1, 1512 * 4, dtv.MOD_QPSK, dtv.ALPHA4, dtv.C2_3)
        v2s_inner = blocks.vector_to_stream(gr.sizeof_char, 1512 * 4)
        carrier_mod = isdbt.carrier_modulation(MODE, SEG_A, CONST_A)

        hier_comb = isdbt.hierarchical_combinator(MODE, SEG_A, SEG_B, 0)
        make_zero_layer_b(tb, hier_comb, 20000)

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
                                          TOTAL_CARRIERS + GUARD_SAMPLES, 0, '')
        gain_blk = blocks.multiply_const_cc(0.0022097087)
        iq_sink = blocks.file_sink(gr.sizeof_gr_complex, iq_file, False)

        tb.connect(src, s2v, rs_enc, e_disp, b_intlv, inner, v2s_inner, carrier_mod)
        tb.connect(carrier_mod, (hier_comb, 0))
        tb.connect(hier_comb, time_intlv, freq_intlv, skiphead, pilot, tmcc_enc,
                   ifft, cp, gain_blk, iq_sink)

        tb.run()

        iq_sz = os.path.getsize(iq_file) if os.path.exists(iq_file) else 0
        self.assertGreater(iq_sz, 0, "TX produced no IQ data")

        import subprocess
        project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        cmd = [
            sys.executable,
            os.path.join(project_dir, 'fullseg_rx.py'),
            '--iq', iq_file,
            '--freq-offset', '0',
            '--guard', '1/8',
            '--layer', 'a',
            '-o', ts_out,
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        self.assertEqual(proc.returncode, 0,
                         f"RX pipeline failed: {proc.stderr[-500:]}")

        ts_sz = os.path.getsize(ts_out) if os.path.exists(ts_out) else 0
        self.assertGreater(ts_sz, 0, "RX produced no TS output from TX IQ")
        self.assertEqual(ts_sz % 188, 0)

        matched, total, offset = compare_ts_auto_align(ts_in, ts_out)
        match_rate = matched / total if total > 0 else 0
        self.assertGreater(match_rate, 0.95,
                           f"OFDM loopback: {matched}/{total} ({match_rate:.1%}), "
                           f"offset={offset}")


if __name__ == '__main__':
    unittest.main(verbosity=2)
