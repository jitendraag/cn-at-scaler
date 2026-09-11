#!/usr/bin/env python3
"""
handshake_race.py - count the round trips before the first byte of your page.

Everything else in this repo is about what happens once the connection is up.
This is about the part before that, which is the part users actually feel,
because it is pure latency and no amount of bandwidth touches it.

  HTTP/1.1 or HTTP/2 over TCP + TLS 1.3
      SYN -> SYN/ACK -> ACK                       1 RTT   (TCP)
      ClientHello -> ServerHello ... Finished     1 RTT   (TLS 1.3)
      GET -> 200                                  1 RTT
                                                  3 RTT total
      (TLS 1.2 made it four. ALPN is free - it rides in the ClientHello,
       which is why HTTP/2 costs no round trips to negotiate and the old
       Upgrade: h2c dance did.)

  HTTP/3 over QUIC, new connection
      Initial (ClientHello inside a QUIC CRYPTO frame) -> Handshake  1 RTT
      GET -> 200                                                     1 RTT
                                                                     2 RTT
      QUIC does not have a transport handshake and then a crypto
      handshake. RFC 9001 s.2.1: there is one handshake.

  HTTP/3 with a session ticket, 0-RTT
      GET travels in the very first flight                           1 RTT
      RFC 9001 s.4.6, and s.9.2 for the catch: early data can be
      replayed by an attacker who captured it, so it is only safe for
      requests you would be happy to serve twice.

    python3 05-http3/handshake_race.py --rtt 60
"""
import argparse, asyncio, os, pickle, socket, ssl, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "04-http2"))


def tcp_tls_ttfb(host, port, path, rtt_label):
    """Wall-clock time from 'no socket' to 'first byte of the response'."""
    t0 = time.time()
    s = socket.create_connection((host, port))
    s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    ctx.set_alpn_protocols(["h2", "http/1.1"])
    s = ctx.wrap_socket(s, server_hostname="localhost")
    alpn = s.selected_alpn_protocol()
    if alpn == "h2":
        import h2_client as hc
        s.sendall(hc.PREFACE)
        s.sendall(hc.frame(hc.SETTINGS, 0, 0, b""))
        enc = hc.Encoder()
        s.sendall(hc.frame(hc.HEADERS, hc.END_HEADERS | hc.END_STREAM, 1,
                           enc.encode([(b":method", b"GET"), (b":path", path.encode()),
                                       (b":scheme", b"https"),
                                       (b":authority", f"{host}:{port}".encode())])))
    else:
        s.sendall(f"GET {path} HTTP/1.1\r\nHost: localhost\r\n\r\n".encode())
    s.recv(1)
    ms = (time.time() - t0) * 1000
    s.close()
    return alpn, ms


async def quic_ttfb(port, path, ticket_path, use_ticket, early=False):
    from aioquic.quic.configuration import QuicConfiguration
    import h3_client as h3c
    cfg = QuicConfiguration(is_client=True, alpn_protocols=["h3"])
    cfg.verify_mode = ssl.CERT_NONE
    if use_ticket and os.path.exists(ticket_path):
        cfg.session_ticket = pickle.load(open(ticket_path, "rb"))

    def save(t):
        pickle.dump(t, open(ticket_path, "wb"))

    t0 = time.time()
    # wait_connected=False lets the request go out in the FIRST flight, next to
    # the ClientHello, as TLS 1.3 early data (RFC 9001 s.4.6). That is what
    # 0-RTT means: not a faster handshake, but no handshake wait at all.
    async with h3c.connect("127.0.0.1", port, configuration=cfg,
                           create_protocol=h3c.H3Client,
                           session_ticket_handler=save,
                           wait_connected=not early) as c:
        await c.get(path, f"127.0.0.1:{port}")
        return (time.time() - t0) * 1000


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rtt", type=float, default=60)
    ap.add_argument("--tcp-port", type=int, default=9443, help="TLS h2 via laggy")
    ap.add_argument("--quic-port", type=int, default=4633, help="QUIC via lossy_udp")
    ap.add_argument("--path", default="/style.css")
    ap.add_argument("--ticket", default="out/race.ticket")
    a = ap.parse_args()

    rtt = a.rtt
    print(f"\n  RTT {rtt:g} ms. Time from nothing to the first response byte.\n")
    print(f"  {'':<42} {'measured':>10}  {'round trips':>12}")
    print("  " + "-" * 68)

    alpn, ms = tcp_tls_ttfb("127.0.0.1", a.tcp_port, a.path, rtt)
    print(f"  {'TCP + TLS 1.3 + ' + (alpn or '?') + ' (new connection)':<42} "
          f"{ms:>8.1f} ms  {ms/rtt:>11.1f}")

    if os.path.exists(a.ticket):
        os.remove(a.ticket)
    ms1 = await quic_ttfb(a.quic_port, a.path, a.ticket, use_ticket=False)
    print(f"  {'QUIC + HTTP/3 (new connection, 1-RTT)':<42} "
          f"{ms1:>8.1f} ms  {ms1/rtt:>11.1f}")

    await asyncio.sleep(0.2)
    ms2 = await quic_ttfb(a.quic_port, a.path, a.ticket, use_ticket=True,
                          early=True)
    print(f"  {'QUIC + HTTP/3 (0-RTT, request in flight 1)':<42} "
          f"{ms2:>8.1f} ms  {ms2/rtt:>11.1f}")
    print()
    print(f"  Cold connection: QUIC saves {ms - ms1:>3.0f} ms - one whole round trip")
    print(f"    that TCP spent agreeing to exist before TLS could start.")
    print(f"  Resumed:         0-RTT saves {ms - ms2:>3.0f} ms against TCP+TLS.")
    print(f"    RFC 9001 s.9.2: early data is replayable, so a 0-RTT request")
    print(f"    must be one you would not mind serving twice.")


if __name__ == "__main__":
    asyncio.run(main())
