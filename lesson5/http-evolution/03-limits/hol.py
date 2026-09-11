#!/usr/bin/env python3
"""
hol.py - head-of-line blocking, the thing HTTP/2 was invented to remove.

HTTP/1.1 lets you pipeline: put six requests on the wire without waiting for
the answers (RFC 2616 s.8.1.2.2). What it does not let you do is answer them
out of order. Responses come back in request order, because on the wire there
is no way to say which response belongs to which request - the ONLY thing
separating them is their position in the byte stream.

So one slow response holds up every fast one behind it. That is head-of-line
blocking, and it is why browsers never turned pipelining on by default.

    python3 03-limits/hol.py --port 8011

Reads: request 1 is slow (the server sleeps), requests 2-6 are instant.
"""
import argparse, socket, threading, time

FAST = ["/style.css", "/app.js", "/logo.png", "/icon.png", "/hero.png"]


def read_one(f):
    head = b""
    while b"\r\n\r\n" not in head:
        c = f.read(1)
        if not c:
            return None
        head += c
    n = 0
    for line in head.decode("latin-1").split("\r\n"):
        if line.lower().startswith("content-length"):
            n = int(line.split(":")[1])
    return head + f.read(n)


def get(path, keep=True):
    return (f"GET {path} HTTP/1.1\r\nHost: site-a.local\r\n"
            f"Connection: {'keep-alive' if keep else 'close'}\r\n\r\n").encode()


def pipelined(host, port, slow):
    order = [f"/big.txt?delay={slow}"] + FAST
    s = socket.create_connection((host, port))
    f = s.makefile("rb")
    t0 = time.time()
    s.sendall(b"".join(get(p) for p in order))      # all six, one flush
    print(f"  sent all {len(order)} requests at t=0.0 ms")
    for p in order:
        read_one(f)
        print(f"    {p:<24} arrived at {(time.time()-t0)*1000:8.1f} ms")
    s.close()
    return (time.time() - t0) * 1000


def parallel(host, port, slow):
    order = [f"/big.txt?delay={slow}"] + FAST
    t0 = time.time()
    done = {}

    def one(p):
        s = socket.create_connection((host, port))
        f = s.makefile("rb")
        s.sendall(get(p, keep=False))
        read_one(f)
        done[p] = (time.time() - t0) * 1000
        s.close()

    ts = [threading.Thread(target=one, args=(p,)) for p in order]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    for p in order:
        print(f"    {p:<24} arrived at {done[p]:8.1f} ms")
    return (time.time() - t0) * 1000


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8011)
    ap.add_argument("--slow", type=float, default=2.0, help="seconds for request 1")
    a = ap.parse_args()

    print(f"\nPIPELINED on ONE connection - request 1 sleeps {a.slow}s server-side")
    t1 = pipelined(a.host, a.port, a.slow)
    print(f"  total {t1:.1f} ms\n")
    print("SAME requests, one connection each")
    t2 = parallel(a.host, a.port, a.slow)
    print(f"  total {t2:.1f} ms\n")
    print(f"  The five fast responses were ready in milliseconds. Pipelined, they")
    print(f"  waited {a.slow*1000:.0f} ms for a file none of them needed.")
    print(f"  HTTP/1.1 has no way to say 'this response is for request 4'.")
