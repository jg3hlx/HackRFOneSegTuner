#!/usr/bin/env python3
"""End-to-end tests: IQ → full-seg encrypted TS."""
import os
import re
import sys
import subprocess
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(__file__))
from ts_util import analyze_ts, top_pids, sync_rate
from calibrate import get_offset, PROJECT_DIR

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')

MIN_PACKETS_FOR_QUALITY = 100


def get_iq_path():
    path = os.path.join(DATA_DIR, 'ch23_test.cf32')
    if os.path.exists(path):
        return path
    fallback = os.path.join(PROJECT_DIR, 'ch23_long.cf32')
    if os.path.exists(fallback):
        return fallback
    return None


def get_iq_path_short():
    """Prefer shorter IQ extract for slow pipelines (Layer B 64QAM)."""
    short = os.path.join(DATA_DIR, 'ch23_test_10s.cf32')
    if os.path.exists(short):
        return short
    return get_iq_path()


def run_fullseg_pipeline(iq_path, output_ts, freq_offset,
                         layer='b', timeout=1800):
    cmd = [
        sys.executable,
        os.path.join(PROJECT_DIR, 'fullseg_rx.py'),
        '--iq', iq_path,
        '--freq-offset', str(freq_offset),
        '--guard', '1/8',
        '--layer', layer,
        '-o', output_ts,
    ]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def parse_tmcc(output):
    """Extract TMCC layer info from pipeline stdout/stderr."""
    layers = {}
    combined = output
    current_layer = None
    for line in combined.split('\n'):
        m = re.match(r'Layer\s+:\s+(\w)', line)
        if m:
            current_layer = m.group(1)
            layers[current_layer] = {}
        elif current_layer:
            if 'Modulation' in line:
                layers[current_layer]['modulation'] = line.split(':')[-1].strip()
            elif 'Code Rate' in line:
                layers[current_layer]['rate'] = line.split(':')[-1].strip()
            elif 'Number of segments' in line:
                layers[current_layer]['segments'] = line.split(':')[-1].strip()
    return layers


class TestFullsegLayerB(unittest.TestCase):
    """Test full-seg (Layer B, 64QAM) pipeline and TS extraction."""

    @classmethod
    def setUpClass(cls):
        cls.iq = get_iq_path_short()
        if cls.iq is None:
            raise unittest.SkipTest("No ch23 IQ data available")
        cls.freq_offset = get_offset(cls.iq)
        cls.tmpdir = tempfile.mkdtemp(prefix='fullseg_b_')
        cls.ts_path = os.path.join(cls.tmpdir, 'fullseg_b.ts')
        cls.proc = run_fullseg_pipeline(cls.iq, cls.ts_path,
                                        cls.freq_offset, layer='b',
                                        timeout=900)
        cls.output_text = (cls.proc.stdout or '') + (cls.proc.stderr or '')
        cls.ts_size = (os.path.getsize(cls.ts_path)
                       if os.path.exists(cls.ts_path) else 0)
        cls.n_packets = cls.ts_size // 188
        if cls.ts_size > 0:
            cls.stats = analyze_ts(cls.ts_path, max_packets=50000)
        else:
            cls.stats = None

    def test_pipeline_exit_code(self):
        self.assertEqual(self.proc.returncode, 0,
                         f"Pipeline failed: {self.proc.stderr[-500:]}")

    def test_tmcc_detects_layer_b(self):
        """TMCC should identify Layer B as 64QAM rate 3/4."""
        tmcc = parse_tmcc(self.output_text)
        self.assertIn('B', tmcc, f"No Layer B in TMCC. Output:\n{self.output_text[:500]}")
        self.assertIn('64QAM', tmcc['B'].get('modulation', ''),
                      f"Expected 64QAM, got: {tmcc['B']}")

    def test_output_188_aligned(self):
        if self.ts_size == 0:
            self.skipTest("No TS output (SNR likely insufficient for 64QAM)")
        self.assertEqual(self.ts_size % 188, 0)

    def test_has_recognizable_pids(self):
        """Encrypted TS should have standard ISDB-T PID structure."""
        if self.n_packets < MIN_PACKETS_FOR_QUALITY:
            self.skipTest(f"Only {self.n_packets} packets (need {MIN_PACKETS_FOR_QUALITY}+ for quality check)")
        pids = self.stats['pids']
        known = {0x0000, 0x0100, 0x0140, 0x0160, 0x0161, 0x1fff}
        found = known & set(pids.keys())
        self.assertTrue(len(found) > 0,
                        f"No known PIDs. Top: "
                        f"{[(hex(p), c) for p, c in top_pids(self.stats, 5)]}")

    def test_video_pid_is_scrambled(self):
        """PID 0x0100 should have MULTI2 scramble control SC=2 or SC=3."""
        if self.n_packets < MIN_PACKETS_FOR_QUALITY:
            self.skipTest(f"Only {self.n_packets} packets")
        if 0x0100 not in self.stats['pids']:
            self.skipTest("No PID 0x0100")

        with open(self.ts_path, 'rb') as f:
            data = f.read()

        n = min(len(data) // 188, 50000)
        sc_23 = total_vid = 0
        for i in range(n):
            off = i * 188
            if data[off] != 0x47:
                continue
            pid = ((data[off + 1] & 0x1f) << 8) | data[off + 2]
            if pid == 0x0100:
                total_vid += 1
                if (data[off + 3] >> 6) & 3 in (2, 3):
                    sc_23 += 1

        if total_vid < 10:
            self.skipTest(f"Too few video packets: {total_vid}")
        self.assertGreater(sc_23 / total_vid, 0.5,
                           f"{sc_23 / total_vid:.1%} scrambled")

    def test_ecm_pid_present(self):
        if self.n_packets < MIN_PACKETS_FOR_QUALITY:
            self.skipTest(f"Only {self.n_packets} packets")
        self.assertIn(0x0140, self.stats['pids'],
                      f"No ECM. Top: {[(hex(p), c) for p, c in top_pids(self.stats, 10)]}")

    def test_sync_rate_above_threshold(self):
        if self.n_packets < MIN_PACKETS_FOR_QUALITY:
            self.skipTest(f"Only {self.n_packets} packets")
        rate = sync_rate(self.stats)
        self.assertGreater(rate, 0.50, f"Sync rate: {rate:.1%}")


class TestFullsegLayerA(unittest.TestCase):
    """Test Layer A via fullseg_rx.py."""

    @classmethod
    def setUpClass(cls):
        cls.iq = get_iq_path()
        if cls.iq is None:
            raise unittest.SkipTest("No ch23 IQ data available")
        cls.freq_offset = get_offset(cls.iq)
        cls.tmpdir = tempfile.mkdtemp(prefix='fullseg_a_')
        cls.ts_path = os.path.join(cls.tmpdir, 'fullseg_a.ts')
        cls.proc = run_fullseg_pipeline(cls.iq, cls.ts_path,
                                        cls.freq_offset, layer='a')
        if os.path.exists(cls.ts_path) and os.path.getsize(cls.ts_path) > 0:
            cls.stats = analyze_ts(cls.ts_path)
        else:
            cls.stats = None

    def test_pipeline_exit_code(self):
        self.assertEqual(self.proc.returncode, 0,
                         f"Pipeline failed: {self.proc.stderr[-500:]}")

    def test_layer_a_sync_rate(self):
        if self.stats is None:
            self.skipTest("No Layer A output")
        rate = sync_rate(self.stats)
        self.assertGreater(rate, 0.95, f"Sync: {rate:.1%}")

    def test_layer_a_has_video(self):
        """One-seg A/V PIDs are in 0x1080-0x10FF range."""
        if self.stats is None:
            self.skipTest("No Layer A output")
        pids = set(self.stats['pids'].keys())
        self.assertTrue(any(0x1080 <= p <= 0x10FF for p in pids),
                        f"No A/V PIDs: {[hex(p) for p in sorted(pids)[:15]]}")


class TestFullsegBothLayers(unittest.TestCase):
    """Test --layer ab produces both outputs."""

    @classmethod
    def setUpClass(cls):
        cls.iq = get_iq_path_short()
        if cls.iq is None:
            raise unittest.SkipTest("No ch23 IQ data available")
        cls.freq_offset = get_offset(cls.iq)
        cls.tmpdir = tempfile.mkdtemp(prefix='fullseg_ab_')
        cls.ts_path = os.path.join(cls.tmpdir, 'fullseg_ab.ts')
        cls.proc = run_fullseg_pipeline(cls.iq, cls.ts_path,
                                        cls.freq_offset, layer='ab',
                                        timeout=900)
        base = cls.ts_path[:-3] if cls.ts_path.endswith('.ts') else cls.ts_path
        cls.a_path = base + '_a.ts'
        cls.b_path = base + '_b.ts'
        cls.output_text = (cls.proc.stdout or '') + (cls.proc.stderr or '')

    def test_pipeline_exit_code(self):
        self.assertEqual(self.proc.returncode, 0,
                         f"Pipeline failed: {self.proc.stderr[-500:]}")

    def test_layer_a_output(self):
        """Layer A (one-seg) should always produce output."""
        self.assertTrue(
            os.path.exists(self.a_path) and os.path.getsize(self.a_path) > 0,
            "Layer A produced no output")

    def test_tmcc_detects_both_layers(self):
        tmcc = parse_tmcc(self.output_text)
        self.assertIn('A', tmcc, "No Layer A in TMCC")
        self.assertIn('B', tmcc, "No Layer B in TMCC")


if __name__ == '__main__':
    unittest.main(verbosity=2)
