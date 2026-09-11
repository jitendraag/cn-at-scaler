#!/usr/bin/env python3
"""
laggy.py - a TCP proxy that adds real latency, because loopback lies.

Every HTTP-versus-HTTP benchmark you have ever seen on localhost is wrong in the
same way: the thing HTTP/1.1, HTTP/2 and HTTP/3 are all fighting is the round
trip, and on loopback a round trip costs about 30 microseconds. Run the
experiment through this and the numbers start meaning something.

    python3 tools/laggy.py 9011 127.0.0.1 8011 --rtt 60

Now port 9011 behaves like a server 60 ms away. The delay is applied for real,
in both directions, RTT/2 each way - it is not subtracted afterwards.
"""
import argparse, socket, threading, time, sys


def pump(src, dst, delay, tag, stats):
    try:
        while True:
            data = src.recv(65536)
            if not data:
                break
            time.sleep(delay)
            dst.sendall(data)
            stats[tag] += len(data)
    except OSError:
        pass
    finally:
        for s in (src, dst):
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass


def serve(listen_port, up_host, up_port, rtt_ms, quiet):
    half = rtt_ms / 2000.0
    ls = socket.socket()
    ls.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    ls.bind(("127.0.0.1", listen_port))
    ls.listen(512)
    n = 0
    if not quiet:
        print(f"laggy: 127.0.0.1:{listen_port} -> {up_host}:{up_port}  "
              f"RTT {rtt_ms} ms ({half*1000:.1f} ms each way)", file=sys.stderr)
    while True:
        c, _ = ls.accept()
        n += 1
        # The TCP handshake itself already cost a real RTT to the client, because
        # we do not accept()...  we do: so charge the connection its own half-RTT
        # before the first byte can move, which is what SYN/SYN-ACK/ACK costs.
        try:
            u = socket.create_connection((up_host, up_port))
        except OSError:
            c.close()
            continue
        stats = {"up": 0, "down": 0}
        time.sleep(half)
        for a, b, tag in ((c, u, "up"), (u, c, "down")):
            threading.Thread(target=pump, args=(a, b, half, tag, stats),
                             daemon=True).start()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("listen_port", type=int)
    ap.add_argument("up_host")
    ap.add_argument("up_port", type=int)
    ap.add_argument("--rtt", type=float, default=60.0, help="milliseconds")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()
    serve(a.listen_port, a.up_host, a.up_port, a.rtt, a.quiet)
