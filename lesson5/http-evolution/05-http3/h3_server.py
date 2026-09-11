#!/usr/bin/env python3
"""
h3_server.py - HTTP/3 over QUIC (RFC 9114 / RFC 9000), via aioquic.

Everything in this file that is not boilerplate is the same handler you have
now read three times: look up a file, set a content type, send a status. That
is the point. HTTP/3 is not a new HTTP. It is HTTP/2's semantics on a transport
that finally understands what streams are.

The difference lives one layer down:

  HTTP/2   streams are a fiction maintained above TCP. TCP delivers ONE ordered
           byte stream, so a lost segment stalls every stream on the connection
           until the retransmit lands - even the ones whose bytes already
           arrived. RFC 9114 s.1.1 says it plainly: "a lost or reordered packet
           causes all active transactions to experience a stall regardless of
           whether that transaction was directly impacted by the lost packet."

  HTTP/3   streams are real. QUIC does loss recovery per stream, so the packet
           that was lost stalls only the stream it belonged to.

    pip install aioquic
    python3 05-http3/h3_server.py 4433 --certs certs
"""
import argparse, asyncio, hashlib, os, sys, time
from urllib.parse import urlparse, parse_qs

from aioquic.asyncio import serve
from aioquic.asyncio.protocol import QuicConnectionProtocol
from aioquic.h3.connection import H3_ALPN, H3Connection
from aioquic.h3.events import HeadersReceived, DataReceived
from aioquic.quic.configuration import QuicConfiguration
from aioquic.quic.events import ProtocolNegotiated, ConnectionTerminated, \
    HandshakeCompleted

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..", "www", "site-a")
TYPES = {".html": "text/html", ".txt": "text/plain", ".css": "text/css",
         ".js": "application/javascript", ".png": "image/png"}


class H3Server(QuicConnectionProtocol):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._http = None

    def quic_event_received(self, event):
        if isinstance(event, ProtocolNegotiated):
            self._http = H3Connection(self._quic)
            print(f"=== QUIC connection, ALPN {event.alpn_protocol!r}",
                  file=sys.stderr, flush=True)
        elif isinstance(event, HandshakeCompleted):
            pass
        elif isinstance(event, ConnectionTerminated):
            print("=== QUIC connection closed", file=sys.stderr, flush=True)
        if self._http is None:
            return
        for h3ev in self._http.handle_event(event):
            if isinstance(h3ev, HeadersReceived):
                # Each request gets its own asyncio task, for the same reason
                # h2_server.py gives each stream a thread: the transport lets
                # you interleave, but only if the application actually does.
                asyncio.ensure_future(self.serve(h3ev.stream_id,
                                                 dict(h3ev.headers)))

    def send(self, sid, status, body, ctype, extra=()):
        hdrs = [(b":status", str(status).encode()),
                (b"content-type", ctype.encode()),
                (b"content-length", str(len(body)).encode()),
                (b"server", b"h3_server/1.0")]
        hdrs += [(k.encode(), v.encode()) for k, v in extra]
        self._http.send_headers(stream_id=sid, headers=hdrs)
        self._http.send_data(stream_id=sid, data=body, end_stream=True)
        self.transmit()
        print(f"  stream {sid:<3} -> {status} {len(body)}B {ctype}",
              file=sys.stderr, flush=True)

    async def serve(self, sid, h):
        target = h.get(b":path", b"/").decode()
        method = h.get(b":method", b"GET").decode()
        u = urlparse(target)
        q = parse_qs(u.query)
        print(f"  stream {sid:<3} <- {method} {target}", file=sys.stderr, flush=True)
        if "delay" in q:
            await asyncio.sleep(float(q["delay"][0]))
        path = u.path + ("index.html" if u.path.endswith("/") else "")
        if path == "/coffee":
            return self.send(sid, 418, b"I'm a teapot, over QUIC.\n", "text/plain")
        fs = os.path.normpath(os.path.join(ROOT, path.lstrip("/")))
        if not fs.startswith(os.path.normpath(ROOT)) or not os.path.isfile(fs):
            return self.send(sid, 404, f"no such thing: {path}\n".encode(),
                             "text/plain")
        body = open(fs, "rb").read()
        etag = '"%s"' % hashlib.sha256(body).hexdigest()[:16]
        if h.get(b"if-none-match", b"").decode() == etag:
            return self.send(sid, 304, b"", "text/plain", [("etag", etag)])
        self.send(sid, 200, body,
                  TYPES.get(os.path.splitext(fs)[1], "application/octet-stream"),
                  [("etag", etag), ("cache-control", "max-age=60")])


async def main(port, certs, ticket_file):
    cfg = QuicConfiguration(is_client=False, alpn_protocols=H3_ALPN,
                            max_datagram_frame_size=65536)
    cfg.load_cert_chain(os.path.join(certs, "cert.pem"),
                        os.path.join(certs, "key.pem"))
    print(f"HTTP/3 on UDP {port}, ALPN {H3_ALPN}", file=sys.stderr)
    print(f"  (UDP. Not TCP. tcpdump 'udp port {port}' if you want to watch.)",
          file=sys.stderr)
    await serve("127.0.0.1", port, configuration=cfg,
                create_protocol=H3Server,
                session_ticket_fetcher=TICKETS.get,
                session_ticket_handler=lambda t: TICKETS.__setitem__(t.ticket, t))
    await asyncio.Future()


TICKETS = {}

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("port", nargs="?", type=int, default=4433)
    ap.add_argument("--certs", default=os.path.join(HERE, "..", "certs"))
    a = ap.parse_args()
    try:
        asyncio.run(main(a.port, a.certs, None))
    except KeyboardInterrupt:
        pass
