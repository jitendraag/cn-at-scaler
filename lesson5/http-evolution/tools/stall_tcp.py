#!/usr/bin/env python3
"""
stall_tcp.py - hold one chunk of a TCP stream, and watch everything behind it wait.

This is head-of-line blocking at the TRANSPORT layer, the one HTTP/2 could not
fix and QUIC was built to fix.

TCP hands the application ONE ordered byte stream. If a segment goes missing,
the receiving kernel has the later segments sitting in its buffer - it just is
not allowed to give them to you, because that would break the ordering
guarantee TCP exists to provide. It waits for the retransmit. Everything queued
behind the hole waits with it, including bytes belonging to HTTP/2 streams that
have nothing to do with the missing segment.

    python3 tools/stall_tcp.py 9020 127.0.0.1 8020 --after 2000 --stall 300

After 2000 bytes have flowed server->client, this proxy stops forwarding for
300 ms and then resumes. Nothing is dropped and nothing is reordered - it is a
plain delay in the middle of one byte stream, which is precisely the shape of
the stall a single lost segment produces.
"""
import argparse, socket, sys, threading, time


def down(src, dst, after, stall_ms, state):
    sent = 0
    stalled = False
    try:
        while True:
            data = src.recv(65536)
            if not data:
                break
            if not stalled and sent + len(data) > after:
                head = data[:max(0, after - sent)]
                if head:
                    dst.sendall(head)
                    sent += len(head)
                data = data[len(head):]
                stalled = True
                state["at"] = time.time()
                print(f"  stall: holding the stream at byte {sent} for "
                      f"{stall_ms} ms", file=sys.stderr, flush=True)
                time.sleep(stall_ms / 1000.0)
                print(f"  stall: released", file=sys.stderr, flush=True)
            dst.sendall(data)
            sent += len(data)
    except OSError:
        pass
    finally:
        for s in (src, dst):
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass


def up(src, dst):
    try:
        while True:
            d = src.recv(65536)
            if not d:
                break
            dst.sendall(d)
    except OSError:
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("listen_port", type=int)
    ap.add_argument("up_host")
    ap.add_argument("up_port", type=int)
    ap.add_argument("--after", type=int, default=2000, help="bytes downstream")
    ap.add_argument("--stall", type=float, default=300, help="milliseconds")
    a = ap.parse_args()

    ls = socket.socket()
    ls.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    ls.bind(("127.0.0.1", a.listen_port))
    ls.listen(64)
    print(f"stall_tcp: :{a.listen_port} -> {a.up_host}:{a.up_port}  "
          f"one {a.stall:g} ms stall after {a.after} downstream bytes",
          file=sys.stderr)
    while True:
        c, _ = ls.accept()
        u = socket.create_connection((a.up_host, a.up_port))
        for s in (c, u):
            s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        st = {}
        threading.Thread(target=up, args=(c, u), daemon=True).start()
        threading.Thread(target=down, args=(u, c, a.after, a.stall, st),
                         daemon=True).start()


if __name__ == "__main__":
    main()
