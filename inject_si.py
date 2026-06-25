#!/usr/bin/env python3
"""Inject ARIB-compliant ISDB-T SI tables for Japanese TV auto-scan.

Uses Oracle-verified test vectors for PAT/NIT/SDT.
Also patches PMT to add stream_identifier_descriptor (0x52).
"""
import argparse
import struct
import time
from datetime import datetime, timedelta, timezone

JST = timezone(timedelta(hours=9))
CRC32_TABLE = None


def _init_crc32():
    global CRC32_TABLE
    CRC32_TABLE = []
    for i in range(256):
        crc = i << 24
        for _ in range(8):
            crc = ((crc << 1) ^ 0x04C11DB7) if crc & 0x80000000 else (crc << 1)
            crc &= 0xFFFFFFFF
        CRC32_TABLE.append(crc)


def mpeg_crc32(data):
    if CRC32_TABLE is None:
        _init_crc32()
    crc = 0xFFFFFFFF
    for b in data:
        crc = ((crc << 8) & 0xFFFFFFFF) ^ CRC32_TABLE[((crc >> 24) ^ b) & 0xFF]
    return crc


def make_ts_packet(pid, payload, cc, pusi=True):
    pkt = bytearray(188)
    pkt[0] = 0x47
    pkt[1] = (0x40 if pusi else 0x00) | ((pid >> 8) & 0x1F)
    pkt[2] = pid & 0xFF
    pkt[3] = 0x10 | (cc & 0x0F)
    off = 5 if pusi else 4
    if pusi:
        pkt[4] = 0x00  # pointer_field
    room = 188 - off
    n = min(len(payload), room)
    pkt[off:off + n] = payload[:n]
    for i in range(off + n, 188):
        pkt[i] = 0xFF
    return bytes(pkt)


def arib_text(text):
    """Encode text for ARIB STD-B24 8-unit code."""
    out = bytearray()
    mode = None
    for ch in text:
        cp = ord(ch)
        if ch == ' ':
            out.append(0x20)
        elif 0x21 <= cp <= 0x7E:
            if mode != 'alnum':
                out.append(0x0E)  # LS1: G1 alphanumeric into GL
                mode = 'alnum'
            out.append(cp)
        else:
            raw = ch.encode('euc_jp')
            if len(raw) == 2 and raw[0] >= 0xA1 and raw[1] >= 0xA1:
                if mode != 'kanji':
                    out.append(0x0F)  # LS0: G0 Kanji into GL
                    mode = 'kanji'
                out.extend((raw[0] & 0x7F, raw[1] & 0x7F))
            else:
                raise ValueError(f'Character outside ARIB/JIS subset: {ch!r}')
    return bytes(out)


# ── Section builders using Oracle-verified format ──

def build_pat(nid, service_id, pmt_pid):
    """PAT: 00 B0 ..."""
    body = struct.pack('>H', nid)         # transport_stream_id
    body += b'\xC1\x00\x00'              # version=0, current, sec/last=0
    body += b'\x00\x00'                  # program_number=0 (NIT)
    body += struct.pack('>H', 0xE010)    # NIT PID
    body += struct.pack('>H', service_id)
    body += struct.pack('>H', 0xE000 | (pmt_pid & 0x1FFF))
    return _wrap(0x00, body, 0xB0)


def build_nit(nid, channel, service_id, remote_key):
    """NIT actual: 40 F0 ..."""
    freq_val = 3312 + 42 * (channel - 13)

    # Network descriptors: network_name(0x40) + system_management(0xFE)
    net_name = arib_text('IWANCOF')
    nd = bytes([0x40, len(net_name)]) + net_name
    nd += bytes([0xFE, 0x02, 0x03, 0x01])

    # TS descriptors: service_list(0x41) + terrestrial(0xFA) + ts_info(0xCD)
    td = bytes([0x41, 0x03]) + struct.pack('>H', service_id) + bytes([0x01])
    td += bytes([0xFA, 0x04]) + struct.pack('>HH', 0x5A5A, freq_val)
    tsi = bytes([remote_key,
                 0x01,    # name_len=0, tx_type_count=1
                 0x0F,    # type-a 64QAM
                 0x01])   # 1 service
    tsi += struct.pack('>H', service_id)
    td += bytes([0xCD, len(tsi)]) + tsi

    body = struct.pack('>H', nid)
    body += b'\xC1\x00\x00'
    body += struct.pack('>H', 0xF000 | len(nd)) + nd
    ts_loop = struct.pack('>H', nid) + struct.pack('>H', nid)
    ts_loop += struct.pack('>H', 0xF000 | len(td)) + td
    body += struct.pack('>H', 0xF000 | len(ts_loop)) + ts_loop
    return _wrap(0x40, body, 0xF0)


def build_sdt(nid, service_id):
    """SDT actual: 42 F0 ..."""
    svc_name = arib_text('IWANCOF')
    svc_desc = bytes([0x48, 3 + len(svc_name), 0x01, 0x00, len(svc_name)]) + svc_name

    body = struct.pack('>H', nid)
    body += b'\xC1\x00\x00'
    body += struct.pack('>H', nid)    # original_network_id
    body += b'\xFF'
    body += struct.pack('>H', service_id)
    body += bytes([0xF1])             # reserved=111, H-EIT=1, pf=1
    body += struct.pack('>H', len(svc_desc) & 0x0FFF)  # running=0, free_CA=0
    body += svc_desc
    return _wrap(0x42, body, 0xF0)


def build_bit(nid):
    """BIT: C4 F0 ..."""
    bc_name = arib_text('IWANCOF')
    bc_desc = bytes([0xD8, len(bc_name)]) + bc_name
    bc_entry = bytes([0x01]) + struct.pack('>H', 0xF000 | len(bc_desc)) + bc_desc

    body = struct.pack('>H', nid)
    body += b'\xC1\x00\x00'
    body += struct.pack('>H', 0xF000)  # first descriptors: empty
    body += struct.pack('>H', 0xF000 | len(bc_entry)) + bc_entry
    return _wrap(0xC4, body, 0xF0)


def build_tot():
    """TOT: 73 70 ... (JST, no local offset descriptor)"""
    now = datetime.now(JST)
    mjd = (now.date() - datetime(1858, 11, 17).date()).days

    def bcd(v):
        return ((v // 10) << 4) | (v % 10)

    body = struct.pack('>H', mjd)
    body += bytes([bcd(now.hour), bcd(now.minute), bcd(now.second)])
    body += struct.pack('>H', 0xF000)  # no descriptors
    return _wrap(0x73, body, 0x70)


def build_eit_pf(nid, service_id, version=1):
    """Build EIT p/f (0x4E). Returns (present_section, following_section)."""
    now = datetime.now(JST)
    start = now.replace(minute=0, second=0, microsecond=0)
    mjd = (start.date() - datetime(1858, 11, 17).date()).days

    def bcd(v):
        return ((v // 10) << 4) | (v % 10)

    event_name = arib_text('IWANCOF HACK RF FULLSEG TESTING')
    event_text = arib_text('Learning together')

    sed_body = b'jpn' + bytes([len(event_name)]) + event_name
    sed_body += bytes([len(event_text)]) + event_text
    short_event = bytes([0x4D, len(sed_body)]) + sed_body

    # component_descriptor: 1080i 16:9, tag=0x00
    video = bytes([0x50, 0x06, 0xF1, 0xB3, 0x00, 0x6A, 0x70, 0x6E])
    # audio_component_descriptor: stereo AAC 48kHz, tag=0x10
    audio = bytes([0xC4, 0x09, 0xF2, 0x03, 0x10, 0x0F, 0xFF, 0x5F,
                   0x6A, 0x70, 0x6E])

    descs = short_event + video + audio

    event = struct.pack('>H', 0x0001)
    event += struct.pack('>H', mjd)
    event += bytes([bcd(start.hour), 0x00, 0x00])
    event += bytes([bcd(3), 0x00, 0x00])  # 3 hours
    event += struct.pack('>H', len(descs))  # running=0, free_CA=0
    event += descs

    ver_byte = 0xC1 | ((version & 0x1F) << 1)

    def make_section(sec_num, events):
        body = struct.pack('>H', service_id)
        body += bytes([ver_byte, sec_num, 0x01])  # last_section_number=1
        body += struct.pack('>H', nid)
        body += struct.pack('>H', nid)
        body += b'\x01\x4E'  # segment_last=1, last_table_id=0x4E
        body += events
        return _wrap(0x4E, body, 0xF0)

    return make_section(0, event), make_section(1, b'')


def build_pmt(service_id, pcr_pid, streams, pmt_pid):
    """Build PMT with stream_identifier_descriptor (0x52).
    streams = [(stream_type, es_pid, component_tag), ...]"""
    body = struct.pack('>H', service_id)
    body += b'\xC1\x00\x00'
    body += struct.pack('>H', 0xE000 | pcr_pid)
    body += struct.pack('>H', 0xF000)  # program_info_length=0

    for stype, es_pid, ctag in streams:
        body += bytes([stype])
        body += struct.pack('>H', 0xE000 | es_pid)
        es_desc = bytes([0x52, 0x01, ctag])  # stream_identifier_descriptor
        body += struct.pack('>H', 0xF000 | len(es_desc))
        body += es_desc

    return _wrap(0x02, body, 0xB0)


def _wrap(table_id, body, prefix_byte):
    """Wrap section body with table_id, length, and CRC32."""
    sec_len = len(body) + 4
    header = bytes([table_id, prefix_byte | ((sec_len >> 8) & 0x0F), sec_len & 0xFF])
    section = header + body
    section += struct.pack('>I', mpeg_crc32(section))
    return section


# ── PAT/PMT parsing ──

def parse_pat(ts_data):
    """Return [(program_number, pid), ...] from PAT."""
    for i in range(len(ts_data) // 188):
        off = i * 188
        if ts_data[off] != 0x47:
            continue
        pid = ((ts_data[off + 1] & 0x1F) << 8) | ts_data[off + 2]
        if pid != 0x0000:
            continue
        ps = off + 4
        if ts_data[off + 3] & 0x20:
            ps = off + 5 + ts_data[off + 4]
        if not (ts_data[off + 1] & 0x40):
            continue
        ptr = ts_data[ps]
        ss = ps + 1 + ptr
        sl = ((ts_data[ss + 1] & 0x0F) << 8) | ts_data[ss + 2]
        progs = []
        p = ss + 8
        pe = ss + 3 + sl - 4
        while p + 4 <= pe:
            pn = (ts_data[p] << 8) | ts_data[p + 1]
            pp = ((ts_data[p + 2] & 0x1F) << 8) | ts_data[p + 3]
            progs.append((pn, pp))
            p += 4
        return progs
    return [(1, 0x1FC8)]


def parse_pmt(ts_data, pmt_pid):
    """Return (service_id, pcr_pid, [(stream_type, es_pid), ...]) from PMT."""
    for i in range(len(ts_data) // 188):
        off = i * 188
        if ts_data[off] != 0x47:
            continue
        pid = ((ts_data[off + 1] & 0x1F) << 8) | ts_data[off + 2]
        if pid != pmt_pid:
            continue
        if not (ts_data[off + 1] & 0x40):
            continue
        ps = off + 4
        if ts_data[off + 3] & 0x20:
            ps = off + 5 + ts_data[off + 4]
        ptr = ts_data[ps]
        ss = ps + 1 + ptr
        if ts_data[ss] != 0x02:
            continue
        sl = ((ts_data[ss + 1] & 0x0F) << 8) | ts_data[ss + 2]
        sid = (ts_data[ss + 3] << 8) | ts_data[ss + 4]
        pcr = ((ts_data[ss + 8] & 0x1F) << 8) | ts_data[ss + 9]
        pi_len = ((ts_data[ss + 10] & 0x0F) << 8) | ts_data[ss + 11]
        p = ss + 12 + pi_len
        pe = ss + 3 + sl - 4
        streams = []
        while p + 5 <= pe:
            stype = ts_data[p]
            es_pid = ((ts_data[p + 1] & 0x1F) << 8) | ts_data[p + 2]
            ei_len = ((ts_data[p + 3] & 0x0F) << 8) | ts_data[p + 4]
            streams.append((stype, es_pid))
            p += 5 + ei_len
        return sid, pcr, streams
    return 1, 0x1FFF, []


# ── Main injection ──

def inject(input_path, output_path, channel, fullseg_ts=None):
    with open(input_path, 'rb') as f:
        ts_data = f.read()

    progs = parse_pat(ts_data)
    svc_progs = [(pn, pp) for pn, pp in progs if pn != 0]
    service_id = svc_progs[0][0] if svc_progs else 1
    pmt_pid = svc_progs[0][1] if svc_progs else 0x1FC8

    _, pcr_pid, oneseg_es = parse_pmt(ts_data, pmt_pid)

    # Detect Layer B ES PIDs from fullseg TS
    fullseg_es = []
    if fullseg_ts:
        with open(fullseg_ts, 'rb') as f:
            fs_data = f.read(188 * 5000)
        fs_progs = parse_pat(fs_data)
        fs_svc = [(pn, pp) for pn, pp in fs_progs if pn != 0]
        if fs_svc:
            _, _, fullseg_es = parse_pmt(fs_data, fs_svc[0][1])

    # Build PMT with both layers
    # Layer B: MPEG-2 video (0x00) + audio (0x10)
    # Layer A: H.264 video (0x81) + audio (0x83) — partial reception tags
    streams = []
    for stype, es_pid in fullseg_es:
        ctag = 0x00 if stype in (0x02, 0x1B) else 0x10
        streams.append((stype, es_pid, ctag))
    for stype, es_pid in oneseg_es:
        ctag = 0x81 if stype in (0x02, 0x1B) else 0x83
        streams.append((stype, es_pid, ctag))

    nid = 0x7FE6
    sid = 0x0430
    remote_key = 7

    main_pcr = pcr_pid
    if fullseg_es:
        for stype, pid in fullseg_es:
            if stype in (0x02, 0x1B):
                main_pcr = pid
                break

    pat = build_pat(nid, sid, pmt_pid)
    pmt = build_pmt(sid, main_pcr, streams, pmt_pid)
    nit = build_nit(nid, channel, sid, remote_key)
    sdt = build_sdt(nid, sid)
    bit = build_bit(nid)
    eit_present, eit_following = build_eit_pf(nid, sid)

    print(f"  nid=0x{nid:04X} sid=0x{sid:04X} CH{channel}")
    print(f"  PMT ES: {[(hex(s), hex(p), hex(c)) for s, p, c in streams]}")

    n = len(ts_data) // 188
    out = []
    cc = {}
    null_idx = 0

    def next_cc(pid):
        c = cc.get(pid, 0)
        cc[pid] = (c + 1) & 0x0F
        return c

    for i in range(n):
        pkt = ts_data[i * 188:(i + 1) * 188]
        if pkt[0] != 0x47:
            continue
        pid = ((pkt[1] & 0x1F) << 8) | pkt[2]

        if pid == 0x0000:
            out.append(make_ts_packet(0x0000, pat, next_cc(0x0000)))
            continue
        if pid == pmt_pid:
            if pkt[1] & 0x40:
                out.append(make_ts_packet(pmt_pid, pmt, next_cc(pmt_pid)))
            continue
        if pid in (0x0010, 0x0012, 0x0014, 0x0024):
            continue
        if pid == 0x0011:
            out.append(make_ts_packet(0x0011, sdt, next_cc(0x0011)))
            continue
        if pid == 0x1FFF:
            null_idx += 1
            r = null_idx % 5
            if r == 1:
                out.append(make_ts_packet(0x0010, nit, next_cc(0x0010)))
                continue
            if r == 2:
                out.append(make_ts_packet(0x0014, build_tot(), next_cc(0x0014)))
                continue
            if r == 3:
                out.append(make_ts_packet(0x0024, bit, next_cc(0x0024)))
                continue
            if r == 4:
                eit_sec = eit_present if (null_idx // 5) % 2 == 0 else eit_following
                out.append(make_ts_packet(0x0012, eit_sec, next_cc(0x0012)))
                continue
        out.append(pkt)

    with open(output_path, 'wb') as f:
        for p in out:
            f.write(p)

    pc = {}
    for p in out:
        pid = ((p[1] & 0x1F) << 8) | p[2]
        pc[pid] = pc.get(pid, 0) + 1
    si = {0x0000: 'PAT', 0x0010: 'NIT', 0x0011: 'SDT', 0x0012: 'EIT',
          0x0014: 'TOT', 0x0024: 'BIT', 0x1FFF: 'NULL'}
    print(f"  {len(out)} packets")
    for pid in sorted(pc):
        if pid <= 0x30 or pid >= 0x1000:
            print(f"    0x{pid:04X} {si.get(pid, ''):4s} {pc[pid]}")


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('input')
    p.add_argument('output')
    p.add_argument('--channel', type=int, default=13)
    p.add_argument('--fullseg', type=str, default=None,
                   help='Fullseg raw TS (to include Layer B ES in PMT)')
    a = p.parse_args()
    inject(a.input, a.output, a.channel, fullseg_ts=a.fullseg)
