#!/usr/bin/env python3
"""
server11.py - an HTTP/1.1 server that implements the things HTTP/1.1 added.

Everything here is a feature that did not exist in RFC 1945 and arrived in
RFC 2068 (Jan 1997) or RFC 2616 (Jun 1999):

  persistent connections by default   RFC 2616 s.8.1.2  ("Connection: close" opts out)
  Host, and therefore virtual hosts   RFC 2616 s.14.23  (400 if a 1.1 request omits it)
  chunked transfer-coding             RFC 2616 s.3.6.1  (send without knowing the length)
  Range / 206 / 416                   RFC 2616 s.14.35  (the reason video seeking works)
  ETag / If-None-Match / If-Match     RFC 2616 s.14.19  (a fingerprint, not a clock)
  Accept-Encoding -> gzip + Vary      RFC 2616 s.14.3, s.14.44
  OPTIONS PUT DELETE TRACE            RFC 2616 s.9
  100 Continue                        RFC 2616 s.8.2.3  (ask before uploading 4 GB)
  pipelining                          RFC 2616 s.8.1.2.2 (and its head-of-line blocking)

Query parameters that exist so you can see things happen:
  ?delay=N    sleep N seconds before responding  (for the pipelining demo)
  ?chunked=1  send the body chunked even though the length is known
  ?big=1      send a large generated body

    python3 02-http11/server11.py 8011
"""
import gzip as gziplib, hashlib, os, socket, socketserver, sys, threading, time, zlib
from email.utils import formatdate
from urllib.parse import urlparse, parse_qs

HERE = os.path.dirname(os.path.abspath(__file__))
VHOSTS = {"site-a.local": os.path.join(HERE, "..", "www", "site-a"),
          "site-b.local": os.path.join(HERE, "..", "www", "site-b")}
DEFAULT = "site-a.local"

REASON = {200: "OK", 204: "No Content", 206: "Partial Content", 301: "Moved Permanently",
          304: "Not Modified", 307: "Temporary Redirect", 400: "Bad Request",
          403: "Forbidden", 404: "Not Found", 405: "Method Not Allowed",
          411: "Length Required", 412: "Precondition Failed",
          416: "Requested Range Not Satisfiable", 418: "I'm a teapot",
          426: "Upgrade Required", 500: "Internal Server Error",
          501: "Not Implemented", 504: "Gateway Timeout"}

TYPES = {".html": "text/html", ".txt": "text/plain", ".css": "text/css",
         ".js": "application/javascript", ".json": "application/json",
         ".png": "image/png", ".ico": "image/x-icon"}
COMPRESSIBLE = ("text/", "application/javascript", "application/json")

COUNTER = {"conns": 0, "reqs": 0}
LOCK = threading.Lock()


class H11(socketserver.StreamRequestHandler):
    timeout = 15

    def log(self, *a):
        print(f"[{time.strftime('%H:%M:%S')}] c{self.cid} r{self.nreq} ", *a,
              file=sys.stderr, flush=True)

    # ---------- response plumbing ----------
    def respond(self, code, body=b"", ctype="text/plain", extra=None, chunked=False,
                head_only=False, close=False):
        extra = list(extra or [])
        lines = [f"HTTP/1.1 {code} {REASON[code]}",
                 f"Date: {formatdate(usegmt=True)}",
                 "Server: server11/1.1 (RFC 2616)"]
        if code not in (204, 304):
            lines.append(f"Content-Type: {ctype}")
            if chunked:
                lines.append("Transfer-Encoding: chunked")
            else:
                lines.append(f"Content-Length: {len(body)}")
        lines += extra
        # Persistence is the default. You have to ask to leave.
        lines.append("Connection: close" if close else "Connection: keep-alive")
        if not close:
            lines.append("Keep-Alive: timeout=15, max=100")
        head = ("\r\n".join(lines) + "\r\n\r\n").encode()
        out = head
        if not head_only and code not in (204, 304):
            if chunked:
                # RFC 2616 s.3.6.1: size in hex, CRLF, bytes, CRLF ... then 0.
                for i in range(0, len(body), 4096):
                    part = body[i:i + 4096]
                    out += f"{len(part):X}\r\n".encode() + part + b"\r\n"
                out += b"0\r\n\r\n"
            else:
                out += body
        # ONE write, not two. Sending the head and the body as separate small
        # segments is the classic write-write-read shape: Nagle holds the second
        # segment until the peer ACKs the first, the peer's ACK is held by
        # delayed-ACK, and every request on a persistent connection costs an
        # extra ~40 ms. See 03-limits/nagle.py - it is worth seeing once.
        self.wfile.write(out)
        self.wfile.flush()
        self.log(f"-> {code} {REASON[code]} {len(head)}B head + "
                 f"{len(body)}B body{' chunked' if chunked else ''}"
                 f"{' CLOSE' if close else ' keep-alive'}")
        return close

    # ---------- one connection, many requests ----------
    def handle(self):
        with LOCK:
            COUNTER["conns"] += 1
            self.cid = COUNTER["conns"]
        self.nreq = 0
        print(f"=== connection {self.cid} opened from port "
              f"{self.client_address[1]}", file=sys.stderr, flush=True)
        try:
            while True:
                if self.one_request():
                    break
        except (socket.timeout, TimeoutError):
            print(f"=== connection {self.cid} idle timeout after {self.nreq} "
                  f"requests", file=sys.stderr, flush=True)
        except (ConnectionResetError, BrokenPipeError):
            pass
        print(f"=== connection {self.cid} closed after {self.nreq} requests",
              file=sys.stderr, flush=True)

    def one_request(self):
        line = self.rfile.readline(8192)
        if not line:
            return True
        line = line.decode("latin-1").strip()
        if not line:
            return False
        self.nreq += 1
        with LOCK:
            COUNTER["reqs"] += 1
        self.log(f"<- {line!r}")
        try:
            method, target, version = line.split()
        except ValueError:
            return self.respond(400, b"malformed request line\n", close=True)

        hdr = {}
        raw_headers = line + "\r\n"
        while True:
            h = self.rfile.readline(8192).decode("latin-1")
            raw_headers += h
            h = h.strip()
            if not h:
                break
            k, _, v = h.partition(":")
            hdr[k.strip().lower()] = v.strip()
        self.hdr, self.raw_headers = hdr, raw_headers

        # RFC 2616 s.14.23: "A client MUST include a Host header field in all
        # HTTP/1.1 request messages ... a server MUST respond with 400."
        if version == "HTTP/1.1" and "host" not in hdr:
            return self.respond(400, b"HTTP/1.1 requires a Host header (RFC 2616 "
                                     b"14.23). This is the whole reason one IP can "
                                     b"serve a thousand sites.\n", close=True)

        # RFC 2616 s.8.1.2: close only if asked, or if the client is 1.0.
        close = ("close" in hdr.get("connection", "").lower()
                 or version == "HTTP/1.0" and "keep-alive" not in
                 hdr.get("connection", "").lower())

        u = urlparse(target)
        q = parse_qs(u.query)
        path = u.path

        if method == "TRACE":
            return self.respond(200, raw_headers.encode(), "message/http", close=close)
        if method == "OPTIONS":
            return self.respond(204, extra=["Allow: GET, HEAD, POST, PUT, DELETE, "
                                            "OPTIONS, TRACE"], close=close)
        if path == "/coffee":
            # RFC 2324 (1 April 1998), reserved by RFC 9110 s.15.5.19 because it
            # "has been widely implemented as an easter egg".
            return self.respond(418, b"I'm a teapot. RFC 2324 was a joke; RFC 9110 "
                                     b"reserved 418 anyway, because too many people "
                                     b"shipped it.\n", close=close)
        if method in ("PUT", "DELETE", "POST"):
            if method != "DELETE" and "content-length" not in hdr \
                    and "chunked" not in hdr.get("transfer-encoding", ""):
                return self.respond(411, b"Length Required\n", close=close)
            if hdr.get("expect", "").lower() == "100-continue":
                # RFC 2616 s.8.2.3: let the client ask before sending 4 GB.
                self.wfile.write(b"HTTP/1.1 100 Continue\r\n\r\n"); self.wfile.flush()
                self.log("-> 100 Continue (body not sent yet)")
            body = self.read_body(hdr)
            return self.respond(200, f"{method} received {len(body)} bytes\n".encode(),
                                close=close)
        if method not in ("GET", "HEAD"):
            return self.respond(405, extra=["Allow: GET, HEAD, POST, PUT, DELETE, "
                                            "OPTIONS, TRACE"], close=close)

        if "delay" in q:
            time.sleep(float(q["delay"][0]))

        # Virtual hosting. Same socket, same IP, different document root.
        host = hdr.get("host", DEFAULT).split(":")[0]
        root = VHOSTS.get(host)
        if root is None:
            root = VHOSTS[DEFAULT]
            self.log(f"   unknown vhost {host!r}, falling back to {DEFAULT}")
        else:
            self.log(f"   vhost {host} -> {os.path.basename(os.path.normpath(root))}")

        if path.endswith("/"):
            path += "index.html"
        fs = os.path.normpath(os.path.join(root, path.lstrip("/")))
        if not fs.startswith(os.path.normpath(root)):
            return self.respond(403, b"no\n", close=close)
        if not os.path.isfile(fs):
            return self.respond(404, f"no such thing: {path}\n".encode(), close=close)

        body = open(fs, "rb").read()
        ctype = TYPES.get(os.path.splitext(fs)[1], "application/octet-stream")
        st = os.stat(fs)
        # RFC 2616 s.14.19. A fingerprint of the bytes, not a timestamp: it does
        # not lose to a one-second clock granularity and it survives a rebuild.
        etag = '"%s"' % hashlib.sha256(body).hexdigest()[:16]
        extra = [f"ETag: {etag}",
                 f"Last-Modified: {formatdate(st.st_mtime, usegmt=True)}",
                 "Cache-Control: max-age=60, must-revalidate",
                 "Accept-Ranges: bytes"]

        # Conditional GET. RFC 2616 s.13.3.4: if you have both, ETag wins.
        inm = [t.strip() for t in hdr.get("if-none-match", "").split(",") if t.strip()]
        if inm and (etag in inm or "*" in inm):
            self.log(f"   If-None-Match matched {etag} -> 304, body not sent")
            return self.respond(304, extra=extra, close=close)

        # Range. RFC 2616 s.14.35. This is why you can drag a video's scrubber.
        rng = hdr.get("range")
        if rng and rng.startswith("bytes="):
            spec = rng[6:].split(",")[0].strip()
            try:
                a, _, b = spec.partition("-")
                if a == "":                      # bytes=-500 -> the last 500
                    start, end = max(0, len(body) - int(b)), len(body) - 1
                else:
                    start = int(a)
                    end = int(b) if b else len(body) - 1
                if start >= len(body) or start > end:
                    raise ValueError
            except ValueError:
                return self.respond(416, b"", extra=[f"Content-Range: bytes */{len(body)}"],
                                    close=close)
            part = body[start:end + 1]
            self.log(f"   Range {spec} -> bytes {start}-{end}/{len(body)} "
                     f"({len(part)}B of {len(body)}B)")
            return self.respond(206, part, ctype,
                                extra=extra + [f"Content-Range: bytes {start}-{end}/{len(body)}"],
                                head_only=(method == "HEAD"), close=close)

        # Content coding. RFC 2068 s.3.5 already had gzip, compress and deflate.
        # Vary tells every cache in the path that this URL has two answers.
        ae = hdr.get("accept-encoding", "")
        if any(ctype.startswith(p) for p in COMPRESSIBLE) and len(body) > 256:
            extra.append("Vary: Accept-Encoding")
            if "gzip" in ae:
                raw = len(body)
                body = gziplib.compress(body, 6)
                extra.append("Content-Encoding: gzip")
                self.log(f"   gzip {raw} -> {len(body)} bytes "
                         f"({100 - 100*len(body)//raw}% saved)")
            elif "deflate" in ae:
                raw = len(body)
                body = zlib.compress(body, 6)
                extra.append("Content-Encoding: deflate")
                self.log(f"   deflate {raw} -> {len(body)} bytes")

        return self.respond(200, body, ctype, extra=extra,
                            chunked=("chunked" in q),
                            head_only=(method == "HEAD"), close=close)

    def read_body(self, hdr):
        if "chunked" in hdr.get("transfer-encoding", "").lower():
            out = b""
            while True:
                n = int(self.rfile.readline().split(b";")[0], 16)
                if n == 0:
                    self.rfile.readline()
                    return out
                out += self.rfile.read(n)
                self.rfile.read(2)
        return self.rfile.read(int(hdr.get("content-length", 0)))


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True
    disable_nagle_algorithm = True     # TCP_NODELAY, same as nginx and Apache


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8011
    print(f"HTTP/1.1 (RFC 2616) on {port} - persistent by default", file=sys.stderr)
    print(f"vhosts: {', '.join(VHOSTS)}", file=sys.stderr)
    Server(("127.0.0.1", port), H11).serve_forever()
