#!/usr/bin/env python3
"""End-to-end tests: IQ → one-seg TS → video."""
import os
import sys
import subprocess
import tempfile
import json
import unittest

sys.path.insert(0, os.path.dirname(__file__))
from ts_util import analyze_ts, top_pids, sync_rate
from calibrate import get_offset, PROJECT_DIR, SAMP_RATE, SUBCARRIER_HZ

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')


def get_iq_path():
    path = os.path.join(DATA_DIR, 'ch23_test.cf32')
    if os.path.exists(path):
        return path
    fallback = os.path.join(PROJECT_DIR, 'ch23_long.cf32')
    if os.path.exists(fallback):
        return fallback
    return None


def run_oneseg_pipeline(iq_path, output_ts, freq_offset, timeout=180):
    cmd = [
        sys.executable,
        os.path.join(PROJECT_DIR, 'offline_test2.py'),
        iq_path,
        '--guard', '1/8',
        '--full-chain',
        '--freq-offset', str(freq_offset),
        '-o', output_ts,
    ]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


class TestOnesegCapture(unittest.TestCase):
    """Test one-seg (Layer A) TS extraction from IQ data."""

    @classmethod
    def setUpClass(cls):
        cls.iq = get_iq_path()
        if cls.iq is None:
            raise unittest.SkipTest("No ch23 IQ data available")
        cls.freq_offset = get_offset(cls.iq)
        cls.tmpdir = tempfile.mkdtemp(prefix='oneseg_test_')
        cls.ts_path = os.path.join(cls.tmpdir, 'oneseg.ts')
        cls.proc = run_oneseg_pipeline(cls.iq, cls.ts_path, cls.freq_offset)
        if os.path.exists(cls.ts_path) and os.path.getsize(cls.ts_path) > 0:
            cls.stats = analyze_ts(cls.ts_path)
        else:
            cls.stats = None

    def test_pipeline_exit_code(self):
        self.assertEqual(self.proc.returncode, 0,
                         f"Pipeline failed: {self.proc.stderr[-500:]}")

    def test_output_exists_and_nonempty(self):
        self.assertTrue(os.path.exists(self.ts_path))
        self.assertGreater(os.path.getsize(self.ts_path), 0, "Output TS is empty")

    def test_188_byte_alignment(self):
        self.assertEqual(os.path.getsize(self.ts_path) % 188, 0)

    def test_sync_rate_above_95pct(self):
        if self.stats is None:
            self.skipTest("No TS output")
        rate = sync_rate(self.stats)
        self.assertGreater(rate, 0.95, f"Sync rate: {rate:.1%}")

    def test_has_pmt(self):
        """ISDB-T one-seg uses PID 0x1fc8 for PMT."""
        if self.stats is None:
            self.skipTest("No TS output")
        self.assertIn(0x1fc8, self.stats['pids'])

    def test_has_av_pids(self):
        """ISDB-T one-seg A/V PIDs are in 0x1080-0x10FF range."""
        if self.stats is None:
            self.skipTest("No TS output")
        pids = set(self.stats['pids'].keys())
        self.assertTrue(any(0x1080 <= p <= 0x10FF for p in pids),
                        f"No A/V PIDs in {[hex(p) for p in sorted(pids)[:20]]}")

    def test_video_pid_dominant(self):
        """PID 0x1081 (video) should be the most common PID."""
        if self.stats is None:
            self.skipTest("No TS output")
        top = top_pids(self.stats, 1)
        self.assertEqual(top[0][0], 0x1081)

    def test_null_packets_present(self):
        if self.stats is None:
            self.skipTest("No TS output")
        self.assertIn(0x1fff, self.stats['pids'])

    def test_cc_errors_below_10pct(self):
        if self.stats is None:
            self.skipTest("No TS output")
        total_err = sum(self.stats['cc_errors'].values())
        total = self.stats['sync_ok']
        if total == 0:
            self.skipTest("No synced packets")
        self.assertLess(total_err / total, 0.10,
                        f"CC error rate: {total_err / total:.1%}")


class TestOnesegVideo(unittest.TestCase):
    """Test that one-seg TS contains decodable video."""

    @classmethod
    def setUpClass(cls):
        cls.iq = get_iq_path()
        if cls.iq is None:
            raise unittest.SkipTest("No ch23 IQ data available")
        cls.freq_offset = get_offset(cls.iq)
        cls.tmpdir = tempfile.mkdtemp(prefix='oneseg_video_')
        cls.ts_path = os.path.join(cls.tmpdir, 'oneseg.ts')
        run_oneseg_pipeline(cls.iq, cls.ts_path, cls.freq_offset)
        cls.has_ts = os.path.exists(cls.ts_path) and os.path.getsize(cls.ts_path) > 0

    def test_ffprobe_detects_video(self):
        if not self.has_ts:
            self.skipTest("No TS output")
        try:
            proc = subprocess.run(
                ['ffprobe', '-v', 'error', '-show_streams',
                 '-print_format', 'json', self.ts_path],
                capture_output=True, text=True, timeout=30)
        except FileNotFoundError:
            self.skipTest("ffprobe not available")
        info = json.loads(proc.stdout)
        codecs = [s.get('codec_type') for s in info.get('streams', [])]
        self.assertIn('video', codecs, f"Streams: {codecs}")

    def test_ffprobe_detects_audio(self):
        if not self.has_ts:
            self.skipTest("No TS output")
        try:
            proc = subprocess.run(
                ['ffprobe', '-v', 'error', '-show_streams',
                 '-print_format', 'json', self.ts_path],
                capture_output=True, text=True, timeout=30)
        except FileNotFoundError:
            self.skipTest("ffprobe not available")
        info = json.loads(proc.stdout)
        codecs = [s.get('codec_type') for s in info.get('streams', [])]
        self.assertIn('audio', codecs, f"Streams: {codecs}")

    def test_ffmpeg_extracts_frame(self):
        if not self.has_ts:
            self.skipTest("No TS output")
        frame = os.path.join(self.tmpdir, 'frame.png')
        try:
            subprocess.run(
                ['ffmpeg', '-y', '-i', self.ts_path, '-frames:v', '1', frame],
                capture_output=True, text=True, timeout=30)
        except FileNotFoundError:
            self.skipTest("ffmpeg not available")
        self.assertTrue(os.path.exists(frame), "No frame extracted")
        self.assertGreater(os.path.getsize(frame), 100, "Frame too small")


if __name__ == '__main__':
    unittest.main(verbosity=2)
