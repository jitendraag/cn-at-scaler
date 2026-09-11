#!/usr/bin/env bash
# demos.sh - every HTTP/1.1 feature the doc lists, on the wire, in order.
#   tools/lab.sh up  &&  02-http11/demos.sh
set -u
cd "$(dirname "$0")/.."
T="python3 tools/talk.py 8011"
hr() { printf '\n\033[1m--- %s\033[0m\n' "$*"; }

hr "1. persistent by default: three requests, ONE connection"
python3 - <<'EOF'
import socket, time
s = socket.create_connection(("127.0.0.1", 8011)); f = s.makefile("rb")
for p in ["/", "/style.css", "/app.js"]:
    s.sendall(f"GET {p} HTTP/1.1\r\nHost: site-a.local\r\n\r\n".encode())
    head = b""
    while b"\r\n\r\n" not in head: head += f.read(1)
    n = next(int(l.split(":")[1]) for l in head.decode().split("\r\n")
             if l.lower().startswith("content-length"))
    f.read(n)
    print(f"  {p:<12} {head.decode().splitlines()[0]}   socket still open: {not s.fileno()==-1}")
s.close(); print("  three responses, one TCP handshake. RFC 2616 s.8.1.2.")
EOF

hr "2. Connection: close is now the OPT-OUT, not the default"
$T --req "GET /style.css HTTP/1.1" "Host: site-a.local" "Connection: close" "" 2>&1 | grep -Ei '^(HTTP|Connection|---)'

hr "3. Host: one IP, one port, two sites (RFC 2616 s.14.23)"
for h in site-a.local site-b.local; do
  printf '  %-16s -> ' "$h"
  $T --req "GET / HTTP/1.1" "Host: $h" "Connection: close" "" 2>/dev/null | grep -o '<h1>.*</h1>'
done

hr "4. chunked: send a body without knowing its length (RFC 2616 s.3.6.1)"
$T --req "GET /style.css?chunked=1 HTTP/1.1" "Host: site-a.local" "Connection: close" "" 2>/dev/null \
  | sed -n '1,20p' | cat -A | sed 's/\$$//' | head -20

hr "5. Range: 206 Partial Content (RFC 2616 s.14.35) - why video seeking works"
$T --req "GET /big.txt HTTP/1.1" "Host: site-a.local" "Range: bytes=100-199" "Connection: close" "" 2>/dev/null \
  | grep -aE '^(HTTP|Content-Range|Content-Length)'
echo "  the 100 bytes it actually sent:"
$T --req "GET /big.txt HTTP/1.1" "Host: site-a.local" "Range: bytes=100-199" "Connection: close" "" 2>/dev/null \
  | tail -c 101 | sed 's/^/    | /'
echo "  and the last 50 bytes, without knowing the file size:"
$T --req "GET /big.txt HTTP/1.1" "Host: site-a.local" "Range: bytes=-50" "Connection: close" "" 2>/dev/null \
  | grep -E '^(HTTP|Content-Range)'
echo "  and a range past the end:"
$T --req "GET /big.txt HTTP/1.1" "Host: site-a.local" "Range: bytes=999999-" "Connection: close" "" 2>/dev/null \
  | grep -E '^(HTTP|Content-Range)'

hr "6. ETag + If-None-Match: 304, and how many bytes it saved"
ET=$($T --req "HEAD /big.txt HTTP/1.1" "Host: site-a.local" "Connection: close" "" 2>/dev/null | grep -i '^ETag' | cut -d' ' -f2 | tr -d '\r')
echo "  ETag is $ET"
$T --req "GET /big.txt HTTP/1.1" "Host: site-a.local" "If-None-Match: $ET" "Connection: close" "" 2>&1 \
  | grep -E '^(HTTP|ETag|---)'
echo "  200 would have been ~202000 bytes of body. 304 sent 0."

hr "7. Accept-Encoding: gzip, and the Vary that keeps caches honest"
for enc in "identity" "gzip" "deflate"; do
  printf '  Accept-Encoding: %-9s -> ' "$enc"
  $T --req "GET /big.txt HTTP/1.1" "Host: site-a.local" "Accept-Encoding: $enc" "Connection: close" "" 2>/dev/null \
    | grep -aEi '^(Content-Length|Content-Encoding|Vary):' | tr -d '\r' | paste -sd' | '
done
echo "  202000 bytes of repetitive English -> about 3% of its size. Text"
echo "  compresses; that is why HTTP being text mattered less than it looks."
echo "  Vary: Accept-Encoding is the header that stops a cache serving the"
echo "  gzip bytes to a client that never asked for them."

hr "8. OPTIONS, TRACE, and the methods RFC 1945 did not have"
$T --req "OPTIONS * HTTP/1.1" "Host: site-a.local" "Connection: close" "" 2>/dev/null | grep -E '^(HTTP|Allow)'
echo "  TRACE echoes your request back, proxies and all:"
$T --req "TRACE /x HTTP/1.1" "Host: site-a.local" "Via: 1.1 some-proxy" "Connection: close" "" 2>/dev/null | tail -5

hr "9. 100 Continue: ask before uploading four gigabytes (RFC 2616 s.8.2.3)"
python3 - <<'EOF'
import socket, time
s = socket.create_connection(("127.0.0.1", 8011)); s.settimeout(3)
s.sendall(b"PUT /upload HTTP/1.1\r\nHost: site-a.local\r\nContent-Length: 11\r\n"
          b"Expect: 100-continue\r\nConnection: close\r\n\r\n")
print("  sent headers only, no body yet")
print("  <-", s.recv(200).decode().strip().replace("\r\n", " | "))
s.sendall(b"hello world")
print("  <-", s.recv(500).decode().split("\r\n\r\n")[0].splitlines()[0])
s.close()
EOF

hr "10. 418 (RFC 2324, 1 April 1998; reserved by RFC 9110 s.15.5.19)"
$T --req "GET /coffee HTTP/1.1" "Host: site-a.local" "Connection: close" "" 2>/dev/null | head -1
$T --req "GET /coffee HTTP/1.1" "Host: site-a.local" "Connection: close" "" 2>/dev/null | tail -3
