"""Shared frequency offset calibration for test suite.

Caches calibration results to avoid repeating the expensive offset search
across test modules.
"""
import os
import sys
import subprocess
import tempfile

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMP_RATE = 8e6 * 64 / 63
SUBCARRIER_HZ = SAMP_RATE / 8192

_cache = {}
_CACHE_FILE = os.path.join(tempfile.gettempdir(), 'isdbt_cal_cache.txt')


def _load_cache():
    if os.path.exists(_CACHE_FILE):
        try:
            with open(_CACHE_FILE) as f:
                for line in f:
                    parts = line.strip().split('\t')
                    if len(parts) == 2:
                        _cache[parts[0]] = float(parts[1])
        except (ValueError, OSError):
            pass


def _save_cache():
    try:
        with open(_CACHE_FILE, 'w') as f:
            for k, v in _cache.items():
                f.write(f"{k}\t{v}\n")
    except OSError:
        pass


def find_best_offset(iq_path, sc_range=range(3, 16)):
    """Find subcarrier offset that produces the most one-seg TS output."""
    key = os.path.realpath(iq_path)
    _load_cache()
    if key in _cache:
        return _cache[key]

    best_sc, best_sz = 0, 0
    for sc in sc_range:
        hz = -(sc * SUBCARRIER_HZ)
        outf = os.path.join(tempfile.gettempdir(), f'_cal_sc{sc}.ts')
        cmd = [sys.executable, os.path.join(PROJECT_DIR, 'offline_test2.py'),
               iq_path, '--guard', '1/8', '--full-chain',
               '--freq-offset', str(hz), '-o', outf]
        subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        sz = os.path.getsize(outf) if os.path.exists(outf) else 0
        if sz > best_sz:
            best_sz = sz
            best_sc = sc
        if os.path.exists(outf):
            os.remove(outf)

    offset = -(best_sc * SUBCARRIER_HZ)
    _cache[key] = offset
    _save_cache()
    return offset


def get_offset(iq_path):
    """Get cached offset, calibrating if needed."""
    key = os.path.realpath(iq_path)
    _load_cache()
    if key in _cache:
        return _cache[key]
    print(f"  Calibrating frequency offset for {os.path.basename(iq_path)}...")
    offset = find_best_offset(iq_path)
    print(f"  Best offset: {offset:.1f} Hz")
    return offset
