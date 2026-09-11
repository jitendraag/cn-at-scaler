#!/usr/bin/env python3
"""
h2_server.py - an HTTP/2 server, so the hand-written client has something real
to talk to.

The framing state machine here is the `h2` library (pip install h2), not
hand-rolled: the client is the teaching artifact, the server just has to be
correct. What is worth reading is how little of HTTP changed. The handler below
looks up a file and sets a content type, exactly as server11.py does. Same
methods, same status codes, same ETags. HTTP/2 is a new way to write the same
sentence.

Two ways in, both from RFC 9113:
  s.3.3  cleartext, "prior knowledge"  - just start sending the preface
  s.3.2  over TLS, chosen by ALPN      - h2 is negotiated inside the handshake

The third way, the `Upgrade: h2c` dance from RFC 7540, is deprecated by
RFC 9113 s.3.1: "This usage was never widely deployed and is deprecated by this
document." No browser ever shipped cleartext HTTP/2 at all.

    python3 04-http2/h2_server.py 8020                 # h2c
    python3 04-http2/h2_server.py 8443 --tls certs/    # h2 over TLS
"""
import hashlib, os, queue, socket, socketserver, ssl, sys, threading, time
from urllib.parse import urlparse, parse_qs

from h2.config import H2Configuration
from h2.connection import H2Connection
from h2.events import RequestReceived, DataReceived, StreamEnded, WindowUpdated

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..", "www", "site-a")
TYPES = {".html": "text/html", ".txt": "text/plain", ".css": "text/css",
         ".js": "application/javascript", ".png": "image/png"}


class H2Handler(socketserver.BaseRequestHandler):
    def handle(self):
        self.request.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        conn = H2Connection(config=H2Configuration(client_side=False,
                                                   header_encoding="utf-8"))
        conn.initiate_connection()
        self.conn = conn
        # ONE lock guards the connection state, and the bytes it produces are
        # queued to a single writer thread while that lock is still held.
        #
        # The obvious version of this - take the lock, call data_to_send(),
        # release, then sendall() - is WRONG, and wrong in a way that only shows
        # up under load. Two threads each grab a buffer, then race to write them,
        # and the frames reach the wire in a different order than the HPACK
        # encoder produced them in. The peer's dynamic table then disagrees with
        # ours and it decodes an index that does not exist:
        #
        #     IndexError: index 75 is not in either table
        #
        # It is intermittent, it looks like a bug in the decoder, and it is not.
        # Serialising the encoder is not enough; you have to serialise the WRITE.
        # Putting the bytes on a queue while still holding the lock does that,
        # and lets the blocking sendall() happen without holding it.
        self.lock = threading.Lock()
        self.outq = queue.Queue()
        self.writer = threading.Thread(target=self._writer, daemon=True)
        self.writer.start()
        self.flush()
        print(f"=== h2 connection from port {self.client_address[1]}",
              file=sys.stderr, flush=True)
        try:
            while True:
                data = self.request.recv(65536)
                if not data:
                    break
                with self.lock:
                    events = conn.receive_data(data)
                for event in events:
                    if isinstance(event, RequestReceived):
                        # ONE THREAD PER STREAM.
                        #
                        # This matters more than it looks. The first version of
                        # this file called serve() inline, and the multiplexing
                        # demo produced *exactly* the HTTP/1.1 numbers: six
                        # streams, all finishing at 2005 ms, because a 2-second
                        # sleep on stream 1 blocked the read loop that would
                        # have noticed streams 3..11.
                        #
                        # HTTP/2 gives you permission to interleave. It does not
                        # do the interleaving for you. A framing layer that can
                        # multiplex, sitting on a server that handles one request
                        # at a time, is HTTP/1.1 with extra steps.
                        threading.Thread(target=self.safe_serve,
                                         args=(event.stream_id,
                                               dict(event.headers)),
                                         daemon=True).start()
                self.flush()
        except (ConnectionResetError, BrokenPipeError, OSError):
            pass
        self.outq.put(None)
        print(f"=== h2 connection closed", file=sys.stderr, flush=True)

    def _writer(self):
        while True:
            data = self.outq.get()
            if data is None:
                return
            try:
                self.request.sendall(data)
            except OSError:
                return

    def flush(self):
        with self.lock:
            out = self.conn.data_to_send()
            if out:
                self.outq.put(out)     # ordered, because the lock is still held

    def safe_serve(self, sid, headers):
        try:
            self.serve(sid, headers)
        except Exception as e:                                  # noqa: BLE001
            print(f"  stream {sid} died: {e!r}", file=sys.stderr, flush=True)

    def send(self, sid, status, body, ctype, extra=()):
        hdrs = [(":status", str(status)), ("content-type", ctype),
                ("content-length", str(len(body))),
                ("server", "h2_server/1.0"),
                ("date", time.strftime("%a, %d %b %Y %H:%M:%S GMT", time.gmtime()))]
        hdrs += list(extra)
        with self.lock:
            self.conn.send_headers(sid, hdrs)
        self.flush()
        # DATA is the only flow-controlled frame type, and MAX_FRAME_SIZE caps
        # each one at 16 KiB by default (RFC 9113 s.6.5.2). So a 200 KB file is
        # not one frame, it is thirteen - which is precisely what lets the small
        # responses slot in between them.
        i, frames = 0, 0
        while i < len(body):
            with self.lock:
                win = self.conn.local_flow_control_window(sid)
                n = min(len(body) - i, max(0, win), self.conn.max_outbound_frame_size)
                if n:
                    self.conn.send_data(sid, body[i:i + n])
            if n == 0:
                time.sleep(0.002)          # window closed; wait for a WINDOW_UPDATE
                continue
            self.flush()
            i += n
            frames += 1
        with self.lock:
            self.conn.end_stream(sid)
        self.flush()
        print(f"  stream {sid:<3} -> {status} {len(body)}B {ctype}"
              f"{f' in {frames} DATA frames' if frames > 1 else ''}",
              file=sys.stderr, flush=True)

    def serve(self, sid, h):
        target = h.get(":path", "/")
        method = h.get(":method", "GET")
        u = urlparse(target)
        q = parse_qs(u.query)
        print(f"  stream {sid:<3} <- {method} {target}", file=sys.stderr, flush=True)
        if "delay" in q:
            time.sleep(float(q["delay"][0]))
        path = u.path + ("index.html" if u.path.endswith("/") else "")
        if path == "/coffee":
            return self.send(sid, 418, b"I'm a teapot, over HTTP/2.\n", "text/plain")
        fs = os.path.normpath(os.path.join(ROOT, path.lstrip("/")))
        if not fs.startswith(os.path.normpath(ROOT)) or not os.path.isfile(fs):
            return self.send(sid, 404, f"no such thing: {path}\n".encode(), "text/plain")
        body = open(fs, "rb").read()
        etag = '"%s"' % hashlib.sha256(body).hexdigest()[:16]
        if h.get("if-none-match") == etag:
            return self.send(sid, 304, b"", "text/plain", [("etag", etag)])
        self.send(sid, 200, body,
                  TYPES.get(os.path.splitext(fs)[1], "application/octet-stream"),
                  [("etag", etag), ("cache-control", "max-age=60")])


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8020
    srv = Server(("127.0.0.1", port), H2Handler)
    if "--tls" in sys.argv:
        certdir = sys.argv[sys.argv.index("--tls") + 1]
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(os.path.join(certdir, "cert.pem"),
                            os.path.join(certdir, "key.pem"))
        ctx.set_alpn_protocols(["h2", "http/1.1"])
        srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
        print(f"HTTP/2 over TLS on {port}, ALPN offers h2", file=sys.stderr)
    else:
        print(f"HTTP/2 cleartext (h2c, prior knowledge) on {port}", file=sys.stderr)
    srv.serve_forever()
