#!/usr/bin/env python3
"""
h3_client.py - HTTP/3 client, and the head-of-line blocking comparison.

    python3 05-http3/h3_client.py --port 4433 --path /
    python3 05-http3/h3_client.py --port 4433 --multiplex
    python3 05-http3/h3_client.py --port 4433 --zerortt      # 1-RTT vs 0-RTT

Things worth noticing while it runs:

  * There is no TCP handshake and then a TLS handshake. QUIC merges them:
    RFC 9001 s.2.1 carries the TLS 1.3 handshake inside QUIC CRYPTO frames, so
    a new connection reaches application data in ONE round trip, where TCP+TLS
    1.3 needs two and TCP+TLS 1.2 needs three.

  * TLS is not optional. There is no unencrypted QUIC. Even the packet numbers
    and much of the header are protected, which is deliberate: RFC 8999 s.7
    notes that anything a middlebox can read, a middlebox will eventually
    depend on, and then the protocol can never change again.

  * The connection has an ID that is not the four-tuple (RFC 9000 s.5.1). Move
    from Wi-Fi to LTE and your IP changes; the connection does not.
"""
import argparse, asyncio, os, pickle, ssl, sys, time
from urllib.parse import urlparse

from contextlib import asynccontextmanager
import socket

from aioquic.asyncio.client import connect as _connect_v6
from aioquic.asyncio.protocol import QuicConnectionProtocol
from aioquic.quic.connection import QuicConnection
from aioquic.h3.connection import H3_ALPN, H3Connection
from aioquic.h3.events import HeadersReceived, DataReceived
from aioquic.quic.configuration import QuicConfiguration
from aioquic.quic.events import HandshakeCompleted


@asynccontextmanager
async def connect(host, port, *, configuration, create_protocol,
                  session_ticket_handler=None, wait_connected=True):
    """aioquic's own connect() binds an AF_INET6 dual-stack socket.

    That is the right default, but plenty of containers and CI runners have no
    IPv6 at all, and there the socket() call fails outright. Try aioquic's
    version first; fall back to a plain IPv4 socket if the kernel says no.
    Nothing about QUIC changes - it is a UDP socket either way.
    """
    try:
        async with _connect_v6(host, port, configuration=configuration,
                               create_protocol=create_protocol,
                               session_ticket_handler=session_ticket_handler,
                               wait_connected=wait_connected) as p:
            yield p
            return
    except OSError as e:
        if e.errno not in (97, 43):        # EAFNOSUPPORT
            raise
        print("  (no IPv6 here; using an IPv4 UDP socket)", file=sys.stderr)

    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(host, port, family=socket.AF_INET,
                                   type=socket.SOCK_DGRAM)
    addr = infos[0][4]
    if configuration.server_name is None:
        configuration.server_name = host
    connection = QuicConnection(configuration=configuration,
                                session_ticket_handler=session_ticket_handler)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", 0))
    transport, protocol = await loop.create_datagram_endpoint(
        lambda: create_protocol(connection), sock=sock)
    try:
        protocol.connect(addr, transmit=wait_connected)
        if wait_connected:
            await protocol.wait_connected()
        yield protocol
    finally:
        protocol.close()
        await protocol.wait_closed()
        transport.close()


class H3Client(QuicConnectionProtocol):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._http = H3Connection(self._quic)
        self._req = {}
        self.handshake_ms = None
        self._t0 = time.time()

    def quic_event_received(self, event):
        if isinstance(event, HandshakeCompleted):
            self.handshake_ms = (time.time() - self._t0) * 1000
        for e in self._http.handle_event(event):
            st = self._req.get(e.stream_id)
            if st is None:
                continue
            if isinstance(e, HeadersReceived):
                st["headers"] = e.headers
            elif isinstance(e, DataReceived):
                st["body"] += e.data
                if e.stream_ended:
                    st["ms"] = (time.time() - st["t0"]) * 1000
                    st["fut"].set_result(None)

    async def get(self, path, authority):
        sid = self._quic.get_next_available_stream_id()
        fut = asyncio.get_event_loop().create_future()
        self._req[sid] = {"headers": None, "body": b"", "fut": fut,
                          "t0": time.time()}
        self._http.send_headers(stream_id=sid, headers=[
            (b":method", b"GET"), (b":scheme", b"https"),
            (b":authority", authority.encode()), (b":path", path.encode()),
            (b"user-agent", b"h3_client/1.0")], end_stream=True)
        self.transmit()
        await fut
        return sid, self._req[sid]


async def run(a):
    cfg = QuicConfiguration(is_client=True, alpn_protocols=H3_ALPN)
    cfg.verify_mode = ssl.CERT_NONE          # self-signed lab cert
    if a.zerortt and os.path.exists(a.ticket):
        with open(a.ticket, "rb") as f:
            cfg.session_ticket = pickle.load(f)
        print("  resuming with a saved session ticket -> 0-RTT is possible",
              file=sys.stderr)

    def save(ticket):
        with open(a.ticket, "wb") as f:
            pickle.dump(ticket, f)

    t0 = time.time()
    async with connect("127.0.0.1", a.port, configuration=cfg,
                       create_protocol=H3Client,
                       session_ticket_handler=save,
                       wait_connected=True) as c:
        print(f"  QUIC handshake complete in {c.handshake_ms:.1f} ms "
              f"(TLS 1.3 inside QUIC CRYPTO frames, one round trip)",
              file=sys.stderr)
        auth = f"127.0.0.1:{a.port}"
        if not a.multiplex:
            sid, st = await c.get(a.path, auth)
            print()
            for k, v in st["headers"]:
                print(f"  {k.decode()}: {v.decode()}")
            print()
            b = st["body"]
            print(b[:600].decode("utf-8", "replace")
                  + (f"\n  ... [{len(b)} bytes total]" if len(b) > 600 else ""))
            return
        order = [f"/big.txt?delay={a.slow}", "/style.css", "/app.js",
                 "/logo.png", "/icon.png", "/hero.png"]
        tt = time.time()
        res = await asyncio.gather(*[c.get(p, auth) for p in order])
        print(f"\n  all {len(order)} requests on one QUIC connection, "
              f"streams {[r[0] for r in res]}\n")
        for p, (sid, st) in sorted(zip(order, res), key=lambda x: x[1][1]["ms"]):
            print(f"    stream {sid:<3} {p:<24} done at {st['ms']:8.1f} ms  "
                  f"{len(st['body']):>7}B")
        print(f"\n  total {(time.time()-tt)*1000:.1f} ms")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=4433)
    ap.add_argument("--path", default="/")
    ap.add_argument("--multiplex", action="store_true")
    ap.add_argument("--slow", type=float, default=2.0)
    ap.add_argument("--zerortt", action="store_true")
    ap.add_argument("--ticket", default="out/h3.ticket")
    a = ap.parse_args()
    asyncio.run(run(a))
