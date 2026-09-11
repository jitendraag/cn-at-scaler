#!/usr/bin/env python3
"""
hpack_mini.py - HPACK (RFC 7541, May 2015) written out, in about 150 lines.

Header compression is the least glamorous thing HTTP/2 did and the one that
paid for itself fastest. 03-limits/headers.py measured it: 97.5% of the header
bytes a page sends are byte-for-byte repeats. HPACK's answer has three parts,
and none of them is clever:

  1. A STATIC TABLE of 61 header fields everyone already sends (RFC 7541 App A).
     ":method: GET" is index 2. One byte on the wire. Not compressed - indexed.
  2. A DYNAMIC TABLE: anything you have sent before on this connection gets an
     index too. Your 300-byte cookie costs 300 bytes once and 1-2 bytes after.
  3. HUFFMAN CODING (RFC 7541 App B) for the literals that are left, using a
     fixed code built from measured HTTP header text - 'e' is 5 bits, 'X' is 8.

gzip could not be used for headers, by the way, and not for want of trying:
CRIME (2012) showed that compressing attacker-influenced data together with a
secret lets you recover the secret one byte at a time. HPACK's fixed Huffman
table has no adaptive state to leak.

    python3 04-http2/hpack_mini.py         # runs the RFC's own test vectors
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _tables import STATIC_TABLE, HUFFMAN


# ---------------------------------------------------------------- integers
# RFC 7541 s.5.1. Integers are stored in the N low bits of the current byte.
# If they fit, done. If not, the N bits are all ones and the rest follows as
# 7-bit groups with a continuation bit. Same trick as protobuf varints and
# UTF-8 - once you have seen it you see it everywhere.
def enc_int(value, prefix_bits, mask=0):
    limit = (1 << prefix_bits) - 1
    if value < limit:
        return bytes([mask | value])
    out = [mask | limit]
    value -= limit
    while value >= 128:
        out.append(value % 128 + 128)
        value //= 128
    out.append(value)
    return bytes(out)


def dec_int(data, i, prefix_bits):
    limit = (1 << prefix_bits) - 1
    value = data[i] & limit
    i += 1
    if value < limit:
        return value, i
    shift = 0
    while True:
        b = data[i]
        i += 1
        value += (b & 127) << shift
        shift += 7
        if not b & 128:
            return value, i


# ---------------------------------------------------------------- huffman
_DEC = {}
for _sym, (_code, _bits) in enumerate(HUFFMAN):
    _DEC[(_bits, _code)] = _sym


def huff_encode(raw: bytes) -> bytes:
    acc = bits = 0
    out = bytearray()
    for byte in raw:
        code, n = HUFFMAN[byte]
        acc = (acc << n) | code
        bits += n
        while bits >= 8:
            bits -= 8
            out.append((acc >> bits) & 0xFF)
    if bits:                       # pad with the EOS prefix, which is all ones
        out.append(((acc << (8 - bits)) | ((1 << (8 - bits)) - 1)) & 0xFF)
    return bytes(out)


def huff_decode(data: bytes) -> bytes:
    out = bytearray()
    cur = n = 0
    for byte in data:
        for k in range(7, -1, -1):
            cur = (cur << 1) | ((byte >> k) & 1)
            n += 1
            sym = _DEC.get((n, cur))
            if sym is not None:
                if sym == 256:
                    raise ValueError("EOS in the middle of a string")
                out.append(sym)
                cur = n = 0
            elif n > 30:
                raise ValueError("no such Huffman code")
    if n > 7 or cur != (1 << n) - 1:
        raise ValueError("bad padding: must be the EOS prefix, all ones")
    return bytes(out)


def enc_string(raw: bytes, huffman=True) -> bytes:
    if huffman:
        h = huff_encode(raw)
        if len(h) < len(raw):          # only if it actually helps
            return enc_int(len(h), 7, 0x80) + h
    return enc_int(len(raw), 7, 0x00) + raw


def dec_string(data, i):
    is_huff = bool(data[i] & 0x80)
    n, i = dec_int(data, i, 7)
    raw = data[i:i + n]
    return (huff_decode(raw) if is_huff else raw), i + n


# ---------------------------------------------------------------- the tables
class Table:
    """Static table + dynamic table sharing one index space (RFC 7541 s.2.3.3)."""

    def __init__(self, max_size=4096):        # SETTINGS_HEADER_TABLE_SIZE default
        self.dyn = []                          # newest first
        self.max_size = max_size

    @property
    def size(self):
        # RFC 7541 s.4.1: name + value + 32 bytes of assumed overhead.
        return sum(len(n) + len(v) + 32 for n, v in self.dyn)

    def get(self, index):
        if 1 <= index <= len(STATIC_TABLE):
            return STATIC_TABLE[index - 1]
        j = index - len(STATIC_TABLE) - 1
        if 0 <= j < len(self.dyn):
            return self.dyn[j]
        raise IndexError(f"index {index} is not in either table")

    def find(self, name, value):
        """-> (index, exact?) or (None, False). Static first: it is free."""
        part = None
        for i, (n, v) in enumerate(STATIC_TABLE, 1):
            if n == name:
                if v == value:
                    return i, True
                part = part or i
        for j, (n, v) in enumerate(self.dyn):
            if n == name:
                i = len(STATIC_TABLE) + 1 + j
                if v == value:
                    return i, True
                part = part or i
        return part, False

    def add(self, name, value):
        self.dyn.insert(0, (name, value))
        while self.size > self.max_size and self.dyn:
            self.dyn.pop()          # FIFO eviction, oldest out


# ---------------------------------------------------------------- encode
class Encoder:
    def __init__(self, max_size=4096):
        self.table = Table(max_size)

    def encode(self, headers):
        out = bytearray()
        for name, value in headers:
            name = name.encode() if isinstance(name, str) else name
            value = value.encode() if isinstance(value, str) else value
            idx, exact = self.table.find(name, value)
            if exact:
                # s.6.1  1xxxxxxx : the whole field line is one index.
                out += enc_int(idx, 7, 0x80)
            elif idx:
                # s.6.2.1  01xxxxxx : known name, new value, remember it.
                out += enc_int(idx, 6, 0x40) + enc_string(value)
                self.table.add(name, value)
            else:
                # s.6.2.1 with index 0: both new. Remember it.
                out += enc_int(0, 6, 0x40) + enc_string(name) + enc_string(value)
                self.table.add(name, value)
        return bytes(out)


class Decoder:
    def __init__(self, max_size=4096):
        self.table = Table(max_size)

    def decode(self, data):
        out, i = [], 0
        while i < len(data):
            b = data[i]
            if b & 0x80:                                   # 1xxxxxxx indexed
                idx, i = dec_int(data, i, 7)
                out.append(self.table.get(idx))
            elif b & 0x40:                                 # 01xxxxxx literal, index
                idx, i = dec_int(data, i, 6)
                name = self.table.get(idx)[0] if idx else None
                if name is None:
                    name, i = dec_string(data, i)
                value, i = dec_string(data, i)
                self.table.add(name, value)
                out.append((name, value))
            elif b & 0x20:                                 # 001xxxxx table resize
                self.table.max_size, i = dec_int(data, i, 5)
            else:                                          # 0000/0001 no index
                idx, i = dec_int(data, i, 4)
                name = self.table.get(idx)[0] if idx else None
                if name is None:
                    name, i = dec_string(data, i)
                value, i = dec_string(data, i)
                out.append((name, value))
        return out


# ---------------------------------------------------------------- self-test
def _selftest():
    ok = True

    def check(label, got, want):
        nonlocal ok
        good = got == want
        ok &= good
        print(f"  [{'ok' if good else 'FAIL'}] {label}")
        if not good:
            print(f"        got  {got!r}\n        want {want!r}")

    # RFC 7541 C.1: integer representation
    check("C.1.1  10 in a 5-bit prefix", enc_int(10, 5), b"\x0a")
    check("C.1.2  1337 in a 5-bit prefix", enc_int(1337, 5), b"\x1f\x9a\x0a")
    check("C.1.3  42 in an 8-bit prefix", enc_int(42, 8), b"\x2a")

    # RFC 7541 C.4.1: the Huffman-coded literal for "www.example.com"
    check("C.4.1  huffman 'www.example.com'",
          enc_string(b"www.example.com"),
          bytes.fromhex("8c f1e3 c2e5 f23a 6ba0 ab90 f4ff".replace(" ", "")))
    check("C.4.1  huffman round trip",
          huff_decode(huff_encode(b"www.example.com")), b"www.example.com")

    # RFC 7541 C.6.1: a full response header block, Huffman coded, with the
    # dynamic table in play. This is the one that exercises everything.
    d = Decoder()
    first = bytes.fromhex(
        "4882 6402 5885 aec3 771a 4b61 96d0 7abe"
        "9410 54d4 44a8 2005 9504 0b81 66e0 82a6"
        "2d1b ff6e 919d 29ad 1718 63c7 8f0b 97c8"
        "e9ae 82ae 43d3".replace(" ", ""))
    check("C.6.1  decode response 1", d.decode(first),
          [(b":status", b"302"), (b"cache-control", b"private"),
           (b"date", b"Mon, 21 Oct 2013 20:13:21 GMT"),
           (b"location", b"https://www.example.com")])

    # our own encoder against the reference decoder, and vice versa
    hdrs = [(b":method", b"GET"), (b":scheme", b"https"), (b":path", b"/"),
            (b":authority", b"shop.example.com"),
            (b"cookie", b"session=8f14e45fceea167a5a36dedd4bea2543"),
            (b"user-agent", b"Mozilla/5.0 (Macintosh) Chrome/140.0.0.0")]
    e, d2 = Encoder(), Decoder()
    b1 = e.encode(hdrs)
    check("round trip request 1", d2.decode(b1), hdrs)
    b2 = e.encode(hdrs)
    check("round trip request 2", d2.decode(b2), hdrs)
    raw = sum(len(n) + len(v) + 4 for n, v in hdrs)
    print(f"\n  the same header set, three ways:")
    print(f"    HTTP/1.1 text            {raw:>5} bytes")
    print(f"    HPACK, first time        {len(b1):>5} bytes"
          f"   ({100 - 100*len(b1)//raw}% smaller)")
    print(f"    HPACK, second time       {len(b2):>5} bytes"
          f"   ({100 - 100*len(b2)//raw}% smaller)  <- the dynamic table")

    try:
        import hpack
        ref = hpack.Decoder().decode(b1, raw=True)
        check("pypi 'hpack' agrees with our encoder", ref, hdrs)
    except ImportError:
        print("  [skip] pypi 'hpack' not installed, cross-check skipped")
    return ok


if __name__ == "__main__":
    print("HPACK self-test - RFC 7541 test vectors from Appendix C\n")
    sys.exit(0 if _selftest() else 1)
