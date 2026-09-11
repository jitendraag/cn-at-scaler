#!/usr/bin/env python3
"""
fetch_page.py - fetch one page and its assets four ways, and count round trips.

    python3 03-limits/fetch_page.py --port 9011 --rtt 60

  close      HTTP/1.0 behaviour: a fresh TCP connection for every asset.
  keepalive  HTTP/1.1 default:   one connection, one request at a time.
  parallel2  RFC 2616 s.8.1.4:   "SHOULD NOT maintain more than 2 connections".
  parallel6  what browsers actually shipped, because the rule lost.
  pipeline   HTTP/1.1 s.8.1.2.2: send all the requests at once on one connection.

The interesting column is not milliseconds, it is round trips: everything else
is a consequence.
"""
import argparse, socket, threading, time

ASSETS = ["/", "/style.css", "/app.js", "/logo.png", "/hero.png", "/icon.png"]


def req(path, close):
    return (f"GET {path} HTTP/1.1\r\nHost: site-a.local\r\n"
            f"User-Agent: fetch_page/1\r\nAccept: */*\r\n"
            f"Connection: {'close' if close else 'keep-alive'}\r\n\r\n").encode()


def read_one(f):
    """Read exactly one HTTP/1.1 response. Framing is length or delimiter."""
    head = b""
    while b"\r\n\r\n" not in head:
        c = f.read(1)
        if not c:
            return None
        head += c
    lines = head.decode("latin-1").split("\r\n")
    h = {}
    for l in lines[1:]:
        k, _, v = l.partition(":")
        if k:
            h[k.strip().lower()] = v.strip()
    if "chunked" in h.get("transfer-encoding", ""):
        body = b""
        while True:
            n = int(f.readline().split(b";")[0], 16)
            if n == 0:
                f.readline()
                break
            body += f.read(n)
            f.read(2)
    else:
        body = f.read(int(h.get("content-length", 0)))
    return len(head) + len(body)


def one_conn_per_asset(host, port):
    total = rts = 0
    for p in ASSETS:
        s = socket.create_connection((host, port))   # 1 RTT: SYN / SYN-ACK / ACK
        rts += 1
        f = s.makefile("rb")
        s.sendall(req(p, close=True))
        rts += 1                                      # 1 RTT: request / response
        total += read_one(f) or 0
        s.close()
    return total, rts, len(ASSETS)


def one_conn_sequential(host, port):
    s = socket.create_connection((host, port))
    f = s.makefile("rb")
    total, rts = 0, 1
    for p in ASSETS:
        s.sendall(req(p, close=False))
        rts += 1
        total += read_one(f) or 0
    s.close()
    return total, rts, 1


def n_conns(host, port, n):
    buckets = [ASSETS[i::n] for i in range(n)]
    res = [0] * n

    def work(i):
        if not buckets[i]:
            return
        s = socket.create_connection((host, port))
        f = s.makefile("rb")
        for p in buckets[i]:
            s.sendall(req(p, close=False))
            res[i] += read_one(f) or 0
        s.close()

    ts = [threading.Thread(target=work, args=(i,)) for i in range(n)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    deepest = max(len(b) for b in buckets)
    return sum(res), 1 + deepest, min(n, len(ASSETS))


def pipelined(host, port):
    s = socket.create_connection((host, port))
    f = s.makefile("rb")
    s.sendall(b"".join(req(p, close=False) for p in ASSETS))   # all at once
    total = sum(read_one(f) or 0 for _ in ASSETS)
    s.close()
    return total, 2, 1     # 1 RTT to connect, 1 RTT for the whole batch


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8011)
    ap.add_argument("--rtt", type=float, default=0.0, help="label only")
    a = ap.parse_args()

    modes = [("close      (HTTP/1.0)", lambda: one_conn_per_asset(a.host, a.port)),
             ("keepalive  (1 conn)  ", lambda: one_conn_sequential(a.host, a.port)),
             ("parallel2  (RFC says)", lambda: n_conns(a.host, a.port, 2)),
             ("parallel6  (browsers)", lambda: n_conns(a.host, a.port, 6)),
             ("pipelined  (1 batch) ", lambda: pipelined(a.host, a.port))]

    print(f"  {len(ASSETS)} assets, RTT {a.rtt:g} ms")
    print(f"  {'mode':<22} {'bytes':>7} {'round trips':>12} {'TCP conns':>10} {'wall ms':>9}")
    print("  " + "-" * 65)
    for name, fn in modes:
        t0 = time.time()
        b, rts, conns = fn()
        ms = (time.time() - t0) * 1000
        print(f"  {name:<22} {b:>7} {rts:>12} {conns:>10} {ms:>9.1f}")


if __name__ == "__main__":
    main()
