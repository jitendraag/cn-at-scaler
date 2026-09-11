#!/usr/bin/env python3
"""
h2_client.py - HTTP/2 by hand: the preface, the frames, the streams.

HTTP/1.1's problem was never the semantics. GET, 404, ETag, Range - all of that
survives unchanged. What HTTP/2 replaced is the WIRE FORMAT, and it replaced it
with the only thing that was ever going to work: length-prefixed binary frames
with a stream id on every one.

  9-byte frame header (RFC 9113 s.4.1)
  +-----------------------------------------------+
  |                 Length (24)                   |
  +---------------+---------------+---------------+
  |   Type (8)    |   Flags (8)   |
  +-+-------------+---------------+-------------------------------+
  |R|                 Stream Identifier (31)                      |
  +=+=============================================================+
  |                   Frame Payload (0...)                      ...

The stream id is the entire trick. It is why a response can say "I am for
request 4", which is what HTTP/1.1 could never say, which is why HTTP/1.1 had
to answer in order, which is why one slow response blocked five fast ones in
03-limits/hol.py. Twenty-four bits of length, thirty-one bits of stream id.

    python3 04-http2/h2_client.py --port 8020 --path /            # h2c
    python3 04-http2/h2_client.py --port 8443 --tls --path /      # h2 over TLS
    python3 04-http2/h2_client.py --port 8020 --multiplex         # the point
"""
import argparse, os, socket, ssl, struct, sys, threading, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hpack_mini import Encoder, Decoder

# RFC 9113 s.3.4. Twenty-four octets, and it spells something on purpose: any
# HTTP/1.1 server that receives it sees a request for method "PRI" and gives up,
# rather than trying to interpret the binary that follows as text.
PREFACE = b"PRI * HTTP/2.0\r\n\r\nSM\r\n\r\n"

DATA, HEADERS, PRIORITY, RST_STREAM, SETTINGS, PUSH_PROMISE, PING, GOAWAY, \
    WINDOW_UPDATE, CONTINUATION = range(10)
NAMES = {DATA: "DATA", HEADERS: "HEADERS", PRIORITY: "PRIORITY",
         RST_STREAM: "RST_STREAM", SETTINGS: "SETTINGS",
         PUSH_PROMISE: "PUSH_PROMISE", PING: "PING", GOAWAY: "GOAWAY",
         WINDOW_UPDATE: "WINDOW_UPDATE", CONTINUATION: "CONTINUATION"}
END_STREAM, END_HEADERS, ACK = 0x1, 0x4, 0x1

# RFC 9113 s.6.5.2, with the defaults the RFC gives.
SETTINGS_NAMES = {1: "HEADER_TABLE_SIZE",      # default 4096
                  2: "ENABLE_PUSH",            # default 1
                  3: "MAX_CONCURRENT_STREAMS", # default: no limit
                  4: "INITIAL_WINDOW_SIZE",    # default 65535
                  5: "MAX_FRAME_SIZE",         # default 16384
                  6: "MAX_HEADER_LIST_SIZE",  # default: unlimited
                  8: "ENABLE_CONNECT_PROTOCOL"}   # RFC 8441, for WebSocket


def frame(ftype, flags, stream, payload=b""):
    if len(payload) >= 1 << 24:
        raise ValueError("a frame cannot exceed 2^24-1 bytes; that is the 24-bit length")
    return struct.pack(">I", len(payload))[1:] + bytes([ftype, flags]) \
        + struct.pack(">I", stream & 0x7FFFFFFF) + payload


def read_frame(f):
    head = f.read(9)
    if len(head) < 9:
        return None
    length = int.from_bytes(head[0:3], "big")
    ftype, flags = head[3], head[4]
    stream = int.from_bytes(head[5:9], "big") & 0x7FFFFFFF
    return ftype, flags, stream, f.read(length), head


def describe(ftype, flags, stream, payload, head, verbose):
    if not verbose:
        return
    fl = []
    if flags & END_STREAM and ftype in (DATA, HEADERS):
        fl.append("END_STREAM")
    if flags & END_HEADERS and ftype in (HEADERS, PUSH_PROMISE, CONTINUATION):
        fl.append("END_HEADERS")
    if flags & ACK and ftype in (SETTINGS, PING):
        fl.append("ACK")
    print(f"  <- {head.hex(' ')}  {NAMES.get(ftype, hex(ftype)):<13} "
          f"len={len(payload):<5} stream={stream:<3} {','.join(fl)}",
          file=sys.stderr)
    if ftype == SETTINGS and not flags & ACK:
        for i in range(0, len(payload), 6):
            k, v = struct.unpack(">HI", payload[i:i + 6])
            print(f"       {SETTINGS_NAMES.get(k, k)} = {v}", file=sys.stderr)
    if ftype == GOAWAY:
        last, err = struct.unpack(">II", payload[:8])
        print(f"       last_stream={last} error={err} {payload[8:]!r}", file=sys.stderr)


class H2:
    def __init__(self, host, port, tls=False, verbose=True):
        self.verbose = verbose
        s = socket.create_connection((host, port))
        s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        if tls:
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            # RFC 9113 s.3.2: over TLS, HTTP/2 is negotiated by ALPN (RFC 7301).
            # No Upgrade dance, no extra round trip - the protocol is chosen
            # inside the handshake you were already paying for.
            ctx.set_alpn_protocols(["h2", "http/1.1"])
            s = ctx.wrap_socket(s, server_hostname="localhost")
            proto = s.selected_alpn_protocol()
            if self.verbose:
                print(f"  TLS {s.version()}  ALPN negotiated: {proto!r}",
                      file=sys.stderr)
            if proto != "h2":
                raise SystemExit(f"server would not speak h2 (got {proto!r})")
        elif self.verbose:
            # RFC 9113 s.3.3: cleartext by prior knowledge. The h2c Upgrade
            # dance of RFC 7540 was deprecated by RFC 9113 s.3.1 - it was never
            # widely deployed, and no browser ever shipped cleartext HTTP/2.
            print("  h2c by prior knowledge (no Upgrade dance; RFC 9113 s.3.3)",
                  file=sys.stderr)
        self.s, self.f = s, s.makefile("rb")
        self.enc, self.dec = Encoder(), Decoder()
        self.next_id = 1
        self.lock = threading.Lock()
        self.streams = {}
        self.send(PREFACE, raw=True)
        if self.verbose:
            print(f"  -> preface {PREFACE!r}", file=sys.stderr)
        self.send(frame(SETTINGS, 0, 0,
                        struct.pack(">HI", 4, 1 << 20) +      # INITIAL_WINDOW_SIZE
                        struct.pack(">HI", 5, 16384)))        # MAX_FRAME_SIZE
        # Give ourselves a big connection-level window so a big body does not
        # stall on flow control while we are trying to demonstrate something else.
        self.send(frame(WINDOW_UPDATE, 0, 0, struct.pack(">I", 1 << 24)))

    def send(self, data, raw=False):
        with self.lock:
            self.s.sendall(data)

    def request(self, method, path, authority, extra=()):
        """Open a new stream. Odd ids, client side (RFC 9113 s.5.1.1)."""
        with self.lock:
            sid = self.next_id
            self.next_id += 2
        hdrs = [(b":method", method.encode()), (b":path", path.encode()),
                (b":scheme", b"http"), (b":authority", authority.encode())]
        hdrs += [(k.encode(), v.encode()) for k, v in extra]
        block = self.enc.encode(hdrs)
        if self.verbose:
            plain = sum(len(k) + len(v) + 4 for k, v in hdrs)
            print(f"  -> HEADERS stream={sid} {method} {path}  "
                  f"{plain}B of text -> {len(block)}B hpack", file=sys.stderr)
        self.send(frame(HEADERS, END_HEADERS | END_STREAM, sid, block))
        self.streams[sid] = {"headers": None, "body": b"", "done": False,
                             "t": time.time()}
        return sid

    def pump(self, until_done=None):
        """Read frames until the named streams are finished."""
        while True:
            fr = read_frame(self.f)
            if fr is None:
                return
            ftype, flags, sid, payload, head = fr
            describe(ftype, flags, sid, payload, head, self.verbose)
            if ftype == SETTINGS and not flags & ACK:
                self.send(frame(SETTINGS, ACK, 0))
            elif ftype == PING and not flags & ACK:
                self.send(frame(PING, ACK, 0, payload))
            elif ftype == HEADERS and sid in self.streams:
                self.streams[sid]["headers"] = self.dec.decode(payload)
            elif ftype == DATA and sid in self.streams:
                self.streams[sid]["body"] += payload
                if len(payload):
                    self.send(frame(WINDOW_UPDATE, 0, 0, struct.pack(">I", len(payload))))
                    self.send(frame(WINDOW_UPDATE, 0, sid, struct.pack(">I", len(payload))))
            elif ftype == GOAWAY:
                return
            if flags & END_STREAM and sid in self.streams:
                st = self.streams[sid]
                st["done"] = True
                st["ms"] = (time.time() - st["t"]) * 1000
            if until_done and all(self.streams[i]["done"] for i in until_done):
                return

    def close(self):
        try:
            self.send(frame(GOAWAY, 0, 0, struct.pack(">II", 0, 0)))
            self.s.close()
        except OSError:
            pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8020)
    ap.add_argument("--tls", action="store_true")
    ap.add_argument("--path", default="/")
    ap.add_argument("--multiplex", action="store_true",
                    help="one slow request and five fast ones, all at once")
    ap.add_argument("--slow", type=float, default=2.0)
    ap.add_argument("-q", "--quiet", action="store_true")
    a = ap.parse_args()

    c = H2(a.host, a.port, a.tls, verbose=not a.quiet)
    if not a.multiplex:
        sid = c.request("GET", a.path, f"{a.host}:{a.port}")
        c.pump(until_done=[sid])
        st = c.streams[sid]
        print()
        for k, v in st["headers"] or []:
            print(f"  {k.decode()}: {v.decode()}")
        print()
        body = st["body"]
        print(body[:600].decode("utf-8", "replace")
              + (f"\n  ... [{len(body)} bytes total]" if len(body) > 600 else ""))
        c.close()
        return

    t0 = time.time()
    order = [f"/big.txt?delay={a.slow}", "/style.css", "/app.js",
             "/logo.png", "/icon.png", "/hero.png"]
    ids = [c.request("GET", p, f"{a.host}:{a.port}") for p in order]
    print(f"\n  all {len(ids)} requests sent on one connection, "
          f"streams {ids}\n", file=sys.stderr)
    c.pump(until_done=ids)
    print()
    for p, sid in sorted(zip(order, ids), key=lambda x: c.streams[x[1]]["ms"]):
        print(f"    stream {sid:<3} {p:<24} done at "
              f"{c.streams[sid]['ms']:8.1f} ms  {len(c.streams[sid]['body']):>7}B")
    print(f"\n  total {(time.time()-t0)*1000:.1f} ms")
    print(f"  Compare 03-limits/hol.py: same six requests, one connection,")
    print(f"  HTTP/1.1 pipelined - everything waited for the slow one.")
    c.close()


if __name__ == "__main__":
    main()
