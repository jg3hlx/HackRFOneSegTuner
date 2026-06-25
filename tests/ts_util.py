"""MPEG-TS packet analysis utilities."""
import struct


def analyze_ts(path, max_packets=None):
    """Analyze a 188-byte TS file and return statistics."""
    with open(path, 'rb') as f:
        data = f.read()

    n_packets = len(data) // 188
    if max_packets and n_packets > max_packets:
        n_packets = max_packets

    stats = {
        'file_size': len(data),
        'total_packets': len(data) // 188,
        'sync_ok': 0,
        'pids': {},
        'tei_count': 0,
        'sc_dist': {0: 0, 1: 0, 2: 0, 3: 0},
        'cc_errors': {},
    }

    last_cc = {}
    for i in range(n_packets):
        off = i * 188
        if off + 188 > len(data):
            break
        sync = data[off]
        if sync != 0x47:
            continue
        stats['sync_ok'] += 1

        b1, b2, b3 = data[off + 1], data[off + 2], data[off + 3]
        tei = (b1 >> 7) & 1
        pid = ((b1 & 0x1f) << 8) | b2
        sc = (b3 >> 6) & 3
        af = (b3 >> 4) & 3
        cc = b3 & 0x0f

        if tei:
            stats['tei_count'] += 1
        stats['pids'][pid] = stats['pids'].get(pid, 0) + 1
        stats['sc_dist'][sc] += 1

        if pid in last_cc and af in (1, 3):
            expected = (last_cc[pid] + 1) & 0x0f
            if cc != expected:
                stats['cc_errors'][pid] = stats['cc_errors'].get(pid, 0) + 1
        last_cc[pid] = cc

    return stats


def top_pids(stats, n=10):
    """Return top N PIDs by packet count."""
    return sorted(stats['pids'].items(), key=lambda x: -x[1])[:n]


def sync_rate(stats):
    if stats['total_packets'] == 0:
        return 0.0
    return stats['sync_ok'] / stats['total_packets']
