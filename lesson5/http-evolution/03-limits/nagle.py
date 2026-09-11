#!/usr/bin/env python3
"""
nagle.py - why keep-alive can be SLOWER than closing the connection.

The first version of server11.py wrote the response head and the response body
with two separate write() calls. On a persistent connection that produces the
write-write-read pattern, and TCP punishes it:

  Nagle (RFC 896, 1984)  : do not send a small segment while an earlier small
                           segment is still unacknowledged.
  Delayed ACK (RFC 1122) : do not acknowledge immediately; wait up to 500 ms
                           (40 ms on Linux) in case you have data to piggyback.

Server writes the head -> goes out immediately (nothing unacked).
Server writes the body -> Nagle holds it, because the head is unacked.
Client has nothing to send, so it holds the ACK for 40 ms.
Body arrives 40 ms late. Every request after the first.

Six assets on one connection: 240 ms of pure protocol interaction, on loopback,
with no network at all. The fix is one write, not two - and TCP_NODELAY.

    python3 03-limits/nagle.py --port 8011
"""
import argparse, socket, time


def timed_run(host, port, paths):
    s = socket.create_connection((host, port))
    f = s.makefile("rb")
    out = []
    for p in paths:
        t = time.time()
        s.sendall(f"GET {p} HTTP/1.1\r\nHost: site-a.local\r\n"
                  f"Connection: keep-alive\r\n\r\n".encode())
        head = b""
        while b"\r\n\r\n" not in head:
            head += f.read(1)
        n = 0
        for line in head.decode("latin-1").split("\r\n"):
            if line.lower().startswith("content-length"):
                n = int(line.split(":")[1])
        f.read(n)
        out.append((time.time() - t) * 1000)
    s.close()
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8011)
    a = ap.parse_args()
    paths = ["/style.css", "/app.js", "/logo.png", "/icon.png", "/hero.png"]
    t = timed_run(a.host, a.port, paths)
    for p, ms in zip(paths, t):
        flag = "   <-- delayed ACK" if ms > 25 else ""
        print(f"  {p:<14} {ms:7.1f} ms{flag}")
    print(f"  {'total':<14} {sum(t):7.1f} ms")
    print()
    print("  If requests 2..n each cost ~40 ms on loopback, the server is doing")
    print("  write(head); write(body). Coalesce them, and set TCP_NODELAY.")
