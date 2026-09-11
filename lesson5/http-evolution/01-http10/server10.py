#!/usr/bin/env python3
"""
server10.py - an HTTP/1.0 server, deliberately faithful to RFC 1945 (May 1996).

It is period-accurate on purpose. Everything it refuses to do is something
RFC 1945 genuinely did not have:

  * three methods only: GET, HEAD, POST          (RFC 1945 s.8)
  * sixteen status codes only                     (RFC 1945 s.9)
  * sixteen header fields only                    (RFC 1945 s.10)
  * no Host header, so one server = one site      (Host arrives in RFC 2068)
  * no Connection header, no keep-alive
  * ONE RESPONSE PER TCP CONNECTION, ALWAYS       (RFC 1945 s.1.3)

That last line is the whole point of the hour. Run it, ask it for the ten
assets of a page, and count the handshakes.

    python3 01-http10/server10.py 8010
"""
import os, socket, socketserver, sys, time, hashlib
from email.utils import formatdate, parsedate_to_datetime

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "www", "site-a")

# RFC 1945 section 9. This is the complete list. All of it.
STATUS = {
    200: "OK",                    201: "Created",
    202: "Accepted",              204: "No Content",
    300: "Multiple Choices",      301: "Moved Permanently",
    302: "Moved Temporarily",     304: "Not Modified",
    400: "Bad Request",           401: "Unauthorized",
    403: "Forbidden",             404: "Not Found",
    500: "Internal Server Error", 501: "Not Implemented",
    502: "Bad Gateway",           503: "Service Unavailable",
}

TYPES = {".html": "text/html", ".txt": "text/plain", ".css": "text/css",
         ".js": "application/javascript", ".json": "application/json",
         ".png": "image/png", ".jpg": "image/jpeg", ".ico": "image/x-icon"}


class H10(socketserver.StreamRequestHandler):
    timeout = 10

    def log(self, *a):
        print(f"[{time.strftime('%H:%M:%S')}] {self.client_address[1]:>5} ",
              *a, file=sys.stderr, flush=True)

    def send(self, code, body=b"", ctype="text/plain", extra=(), head_only=False):
        head = [f"HTTP/1.0 {code} {STATUS[code]}",
                f"Date: {formatdate(usegmt=True)}",
                "Server: server10/1.0 (RFC 1945)"]
        if body or code == 200:
            head += [f"Content-Type: {ctype}", f"Content-Length: {len(body)}"]
        head += list(extra)
        raw = ("\r\n".join(head) + "\r\n\r\n").encode()
        self.wfile.write(raw if head_only else raw + body)
        self.log(f"-> {code} {STATUS[code]}  {len(body)}B body  "
                 f"{len(raw)}B headers -> CLOSING")

    def handle(self):
        # Read exactly one request. There will never be a second one on this
        # socket, because HTTP/1.0 does not have persistent connections.
        line = self.rfile.readline(8192).decode("latin-1").strip()
        if not line:
            return
        self.log(f"<- {line!r}")
        try:
            method, target, version = line.split()
        except ValueError:
            return self.send(400, b"malformed request line\n")

        headers = {}
        while True:
            h = self.rfile.readline(8192).decode("latin-1").strip()
            if not h:
                break
            k, _, v = h.partition(":")
            headers[k.strip().lower()] = v.strip()

        if headers.get("host"):
            # RFC 1945 has no Host. A 1.0 server that receives one ignores it,
            # which is exactly why one IP could serve only one website.
            self.log(f"   (ignoring Host: {headers['host']} - HTTP/1.0 has no vhosts)")

        if method not in ("GET", "HEAD", "POST"):
            return self.send(501, f"{method} is not in RFC 1945. "
                                  f"Try GET, HEAD or POST.\n".encode())

        if method == "POST":
            n = int(headers.get("content-length", 0))
            body = self.rfile.read(n)
            return self.send(200, b"received %d bytes\n" % len(body))

        path = target.split("?")[0]
        if path.endswith("/"):
            path += "index.html"
        fs = os.path.normpath(os.path.join(ROOT, path.lstrip("/")))
        if not fs.startswith(os.path.normpath(ROOT)):
            return self.send(403, b"no\n")
        if not os.path.isfile(fs):
            return self.send(404, f"no such thing: {path}\n".encode())

        st = os.stat(fs)
        lastmod = formatdate(st.st_mtime, usegmt=True)

        # If-Modified-Since / Last-Modified / Expires: caching existed in 1.0,
        # but this is the whole vocabulary. There is no Cache-Control, no ETag,
        # no max-age, no must-revalidate, no stale-while-revalidate.
        ims = headers.get("if-modified-since")
        if ims:
            try:
                if int(parsedate_to_datetime(ims).timestamp()) >= int(st.st_mtime):
                    self.log("   If-Modified-Since matched")
                    return self.send(304, b"")
            except (TypeError, ValueError):
                pass  # RFC 1945: an unparseable date must be ignored, not 400'd

        body = open(fs, "rb").read()
        ctype = TYPES.get(os.path.splitext(fs)[1], "application/octet-stream")
        self.send(200, body, ctype,
                  extra=[f"Last-Modified: {lastmod}",
                         f"Expires: {formatdate(time.time() + 60, usegmt=True)}"],
                  head_only=(method == "HEAD"))


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8010
    print(f"HTTP/1.0 (RFC 1945) on {port} - one response per connection, always",
          file=sys.stderr)
    Server(("127.0.0.1", port), H10).serve_forever()
