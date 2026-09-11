#!/usr/bin/env python3
"""
lossy_udp.py - drop real UDP datagrams, so QUIC has to really recover.

The TCP side of this comparison (tools/stall_tcp.py) delays a chunk of one
ordered byte stream. This side does the harsher thing: it deletes datagrams
outright and lets QUIC's own loss detection (RFC 9002) notice and retransmit.

    python3 tools/lossy_udp.py 4533 127.0.0.1 4433 --loss 0.03 --skip 12

  --loss P   drop each datagram with probability P, server->client
  --skip N   never drop the first N datagrams, so the handshake completes
             and you are measuring data loss rather than connection setup
  --rtt MS   add MS milliseconds of round-trip delay, half in each direction,
             so that round trips cost something and 0-RTT has a point
"""
import argparse, random, socket, sys, threading, time


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("listen_port", type=int)
    ap.add_argument("up_host")
    ap.add_argument("up_port", type=int)
    ap.add_argument("--loss", type=float, default=0.03)
    ap.add_argument("--skip", type=int, default=12)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--rtt", type=float, default=0.0, help="milliseconds")
    a = ap.parse_args()
    rnd = random.Random(a.seed)

    half = a.rtt / 2000.0

    front = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    front.bind(("127.0.0.1", a.listen_port))
    peers = {}          # client addr -> upstream socket
    stats = {"fwd": 0, "drop": 0, "n": 0}

    def from_upstream(usock, caddr):
        while True:
            try:
                data, _ = usock.recvfrom(65536)
            except OSError:
                return
            stats["n"] += 1
            if stats["n"] > a.skip and rnd.random() < a.loss:
                stats["drop"] += 1
                print(f"  dropped datagram #{stats['n']} ({len(data)} B) "
                      f"server->client", file=sys.stderr, flush=True)
                continue
            stats["fwd"] += 1
            if half:
                threading.Timer(half, front.sendto, (data, caddr)).start()
            else:
                front.sendto(data, caddr)

    print(f"lossy_udp: :{a.listen_port} -> {a.up_host}:{a.up_port}  "
          f"loss={a.loss:.0%} after the first {a.skip} datagrams, "
          f"RTT {a.rtt:g} ms", file=sys.stderr)
    try:
        while True:
            data, caddr = front.recvfrom(65536)
            if caddr not in peers:
                u = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                u.connect((a.up_host, a.up_port))
                peers[caddr] = u
                threading.Thread(target=from_upstream, args=(u, caddr),
                                 daemon=True).start()
            if half:
                threading.Timer(half, peers[caddr].send, (data,)).start()
            else:
                peers[caddr].send(data)
    except KeyboardInterrupt:
        print(f"\n  forwarded {stats['fwd']}, dropped {stats['drop']}",
              file=sys.stderr)


if __name__ == "__main__":
    main()
