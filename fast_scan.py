#!/usr/bin/env python3
"""Fast multi-channel TMCC scanner - captures 5s per channel, checks for one-seg."""
import sys, time, os, subprocess, tempfile, argparse

SAMP_RATE = 8e6 * 64 / 63

parser = argparse.ArgumentParser()
parser.add_argument('--channels', type=str, default=None,
                    help='Comma-separated channels to scan (default: top power + broadcast)')
parser.add_argument('--duration', type=int, default=5)
args = parser.parse_args()

if args.channels:
    channels = [int(c) for c in args.channels.split(',')]
else:
    channels = [52, 49, 55, 54, 53, 50, 47, 44, 22, 26, 28, 20, 21, 23, 24, 25, 27, 13, 14, 15, 16, 17, 18, 19]

print(f"Scanning {len(channels)} channels, {args.duration}s each")
print(f"{'Ch':>3} {'Freq':>10} {'TMCC':>6} {'LayerA':>20} {'LayerB':>20} {'SNR_est':>8}")
print("-" * 80)

for ch in channels:
    freq = 473.143e6 + (ch - 13) * 6e6
    tmpfile = f"/tmp/scan_ch{ch}.cf32"

    # Capture
    cap_cmd = [
        'python3', '/home/iwancof/WorkSpace/SDR/oneseg/capture_iq.py',
        str(ch), '--duration', str(args.duration),
        '--amp', '--if-gain', '8', '--bb-gain', '16',
        '-o', tmpfile
    ]
    proc = subprocess.run(cap_cmd, capture_output=True, text=True, timeout=30)

    if not os.path.exists(tmpfile) or os.path.getsize(tmpfile) < 1e6:
        print(f"{ch:3d} {freq/1e6:10.3f} {'FAIL':>6}")
        continue

    # Run TMCC decode
    test_cmd = [
        'python3', '/home/iwancof/WorkSpace/SDR/oneseg/offline_test2.py',
        tmpfile, '--guard', '1/8'
    ]
    proc2 = subprocess.run(test_cmd, capture_output=True, text=True, timeout=60)
    output = proc2.stdout + proc2.stderr

    tmcc_ok = output.count('TMCC OK')
    tmcc_fail = output.count('TMCC NOT OK') + output.count('TMCC WHAT')

    # Parse layer info
    layer_a = ""
    layer_b = ""
    lines = output.split('\n')
    in_layer = None
    for i, line in enumerate(lines):
        if 'Layer' in line and ': A' in line:
            in_layer = 'A'
        elif 'Layer' in line and ': B' in line:
            in_layer = 'B'
        elif 'Layer' in line and ': C' in line:
            in_layer = None
        elif 'Carrier Modulation' in line and in_layer:
            mod = line.split(':')[-1].strip()
            if in_layer == 'A':
                layer_a = mod
            else:
                layer_b = mod
        elif 'Number of segments' in line and in_layer:
            segs = line.split(':')[-1].strip()
            if in_layer == 'A':
                layer_a += f"/{segs}seg"
            elif in_layer == 'B':
                layer_b += f"/{segs}seg"

    # Estimate SNR from phase error
    snr_est = ""
    phase_errs = []
    for line in lines:
        if 'phase err:' in line:
            try:
                pe = float(line.split('phase err:')[1].strip())
                phase_errs.append(abs(pe))
            except:
                pass
    if phase_errs:
        import math
        avg_pe = sum(phase_errs) / len(phase_errs)
        if avg_pe > 0:
            snr_db = -20 * math.log10(avg_pe)
            snr_est = f"{snr_db:.1f}dB"

    status = f"{tmcc_ok}ok/{tmcc_fail}ng"
    has_oneseg = "1seg" in layer_a or layer_a.endswith("/1seg")
    marker = " <<< ONE-SEG" if has_oneseg else ""

    print(f"{ch:3d} {freq/1e6:10.3f} {status:>6} {layer_a:>20} {layer_b:>20} {snr_est:>8}{marker}")
    sys.stdout.flush()

    os.remove(tmpfile)
