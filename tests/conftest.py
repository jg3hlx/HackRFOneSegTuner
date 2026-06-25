"""Shared fixtures and constants for ISDB-T receiver tests.

IQ test data: tests/data/ch23_test.cf32
Capture: python3 capture_iq.py 23 --amp --auto-gain --duration 30 -o tests/data/ch23_test.cf32
"""
import os

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')

SAMP_RATE = 8e6 * 64 / 63
SUBCARRIER_HZ = SAMP_RATE / 8192
MODE = 3
