#!/usr/bin/env python3
"""
talk.py - send exact bytes to a TCP (or TLS) socket and show exactly what comes back.

telnet is not installed on most machines any more, and `curl` is far too helpful:
it adds headers you did not ask for and hides the ones the server sent. This tool
does neither. What you type is what goes on the wire.

  python3 tools/talk.py 8010 --req "GET / HTTP/1.0" ""
  python3 tools/talk.py 8011 --file reqs/keepalive.txt
  echo -e 'GET / HTTP/1.0\r\n\r' | python3 tools/talk.py 8010 --stdin

Every line given with --req is terminated with CRLF, because HTTP says CRLF and
half the bugs in your life come from someone sending a bare LF. An empty string
argument produces the blank line that ends the header block.

Flags:
  --tls            wrap in TLS (no cert verification; these are self-signed)
  --alpn h2,http/1.1   offer these ALPN protocols and print what was negotiated
  --hex            hexdump the response instead of printing it as text
  --timeout N      stop waiting after N seconds of silence (default 3)
  --keep-open      do not send EOF; useful for keep-alive experiments
"""
import argparse, socket, ssl, sys, time

def hexdump(b, width=16):
    out = []
    for i in range(0, len(b), width):
        chunk = b[i:i + width]
        hexpart = " ".join(f"{c:02x}" for c in chunk)
        txt = "".join(chr(c) if 32 <= c < 127 else "." for c in chunk)
        out.append(f"{i:08x}  {hexpart:<{width*3}} |{txt}|")
    return "\n".join(out)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("port", type=int)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--req", nargs="*", help="request lines; '' gives the blank line")
    ap.add_argument("--file", help="file containing the exact request bytes")
    ap.add_argument("--stdin", action="store_true")
    ap.add_argument("--tls", action="store_true")
    ap.add_argument("--alpn")
    ap.add_argument("--sni", default="localhost")
    ap.add_argument("--hex", action="store_true")
    ap.add_argument("--timeout", type=float, default=3.0)
    ap.add_argument("--keep-open", action="store_true")
    a = ap.parse_args()

    if a.file:
        payload = open(a.file, "rb").read().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
    elif a.stdin:
        payload = sys.stdin.buffer.read()
    elif a.req is not None:
        payload = b"".join(l.encode() + b"\r\n" for l in a.req)
    else:
        sys.exit("give --req, --file or --stdin")

    t0 = time.time()
    s = socket.create_connection((a.host, a.port), timeout=a.timeout)
    if a.tls:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        if a.alpn:
            ctx.set_alpn_protocols(a.alpn.split(","))
        s = ctx.wrap_socket(s, server_hostname=a.sni)
        print(f"--- TLS {s.version()}  ALPN={s.selected_alpn_protocol()!r}", file=sys.stderr)

    print(f"--- sent {len(payload)} bytes", file=sys.stderr)
    s.sendall(payload)
    if not a.keep_open:
        try:
            s.shutdown(socket.SHUT_WR) if not a.tls else None
        except OSError:
            pass

    got = b""
    while True:
        try:
            chunk = s.recv(65536)
        except (socket.timeout, ssl.SSLError, TimeoutError):
            print(f"--- no more data after {a.timeout}s: the server is holding the "
                  f"connection open", file=sys.stderr)
            break
        if not chunk:
            print(f"--- server closed the connection (FIN) at "
                  f"{(time.time()-t0)*1000:.1f} ms", file=sys.stderr)
            break
        got += chunk
    s.close()

    sys.stdout.write(hexdump(got) + "\n" if a.hex else got.decode("utf-8", "replace"))
    print(f"--- received {len(got)} bytes in {(time.time()-t0)*1000:.1f} ms",
          file=sys.stderr)

if __name__ == "__main__":
    main()
