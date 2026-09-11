# HTTP, 1996 to now — the runnable version

Companion code for **CN & Scaler, Session 5**. Every claim on a slide is a
program in here, and every program runs on a laptop with no network.

```
pip install h2 hpack aioquic      # the only three dependencies
./run_all.sh                      # about 40 seconds, everything in slide order
```

Nothing listens on a public interface, everything binds `127.0.0.1`, and the
TLS certificate is a self-signed one you generate yourself. If a port is taken,
every script takes `--port`.

---

## Why the servers are written from scratch

You could show all of this with `curl -v` against nginx. You would learn less.
`curl` is a good client, which means it hides the protocol: it adds headers you
did not ask for, retries things quietly, and prints a tidy summary of a
conversation you never saw. Every server here is small enough to read in one
sitting and refuses to be helpful.

| file | what it is | lines |
|---|---|---|
| `tools/talk.py` | send exact bytes to a socket, print exact bytes back | 90 |
| `tools/laggy.py` | TCP proxy that adds real latency — loopback lies | 60 |
| `tools/stall_tcp.py` | holds one chunk of a TCP stream: head-of-line blocking | 80 |
| `tools/lossy_udp.py` | drops real UDP datagrams so QUIC must recover | 70 |
| `01-http10/server10.py` | HTTP/1.0, period-accurate to RFC 1945 | 130 |
| `02-http11/server11.py` | HTTP/1.1 with the features RFC 2068/2616 added | 260 |
| `04-http2/hpack_mini.py` | HPACK from scratch, passes the RFC 7541 vectors | 230 |
| `04-http2/h2_client.py` | HTTP/2 client from scratch: preface, frames, streams | 230 |
| `04-http2/h2_server.py` | h2 server (framing by the `h2` library) | 160 |
| `05-http3/h3_server.py` | HTTP/3 over QUIC, via `aioquic` | 120 |
| `05-http3/h3_client.py` | HTTP/3 client + the multiplexing comparison | 160 |

---

## Hour 1 — HTTP/1.0 (RFC 1945, May 1996)

```bash
tools/lab.sh up
python3 tools/talk.py 8010 --req "GET / HTTP/1.0" ""
```

`server10.py` is deliberately incapable. Three methods, sixteen status codes,
sixteen headers, no `Host`, and **one response per TCP connection, always**.
Ask it for `OPTIONS` and it says 501, correctly: `OPTIONS` did not exist yet.
Send it a `Host` header and it logs that it is ignoring you, which is why in
1996 every website needed its own IP address.

The thing to watch is the `--- server closed the connection (FIN)` line at the
bottom of every response.

## Hour 2 — HTTP/1.1 (RFC 2068 Jan 1997, RFC 2616 Jun 1999)

```bash
02-http11/demos.sh
```

Ten demos, one per feature: persistent connections, `Connection: close` as the
*opt-out*, virtual hosts, chunked encoding, `Range`/206/416, `ETag` → 304,
`Accept-Encoding` → gzip + `Vary`, `OPTIONS`/`TRACE`, `100 Continue`, and 418.

Measured here: `/big.txt` is 202,000 bytes, and 5,763 gzipped — 2.9%.

## Hour 3 — what it cost

```bash
python3 03-limits/nagle.py     --port 8011
python3 03-limits/fetch_page.py --port 9111 --rtt 150
python3 03-limits/hol.py       --port 8011 --slow 2
python3 03-limits/headers.py   --requests 80
python3 03-limits/framing.py   --port 8011
```

**`nagle.py`** is here because the first draft of `server11.py` had the bug.
`write(head); write(body)` on a persistent connection is the write-write-read
pattern, Nagle holds the second segment, the peer's delayed ACK holds the
acknowledgement for 40 ms, and six assets cost 240 ms *on loopback*. One write
instead of two, plus `TCP_NODELAY`, and it drops to 3 ms. Every HTTP server has
had this bug once.

**`fetch_page.py`** fetches a page and five assets five ways, through
`tools/laggy.py` so the round trips cost something:

```
  6 assets, RTT 150 ms
  mode                     bytes  round trips  TCP conns   wall ms
  close      (HTTP/1.0)     4867           12          6    1369.2
  keepalive  (1 conn)       5095            7          1     985.4
  parallel2  (RFC says)     5095            4          2     607.0
  parallel6  (browsers)     5095            2          6     608.2
  pipelined  (1 batch)      5095            2          1     303.7
```

RFC 2616 §8.1.4 says *"A single-user client SHOULD NOT maintain more than 2
connections with any server or proxy."* Read the last three rows and you can see
exactly why every browser ignored it.

**`hol.py`** is why they never turned pipelining on either. Six requests, one
connection, the first one slow:

```
  pipelined:  every fast asset arrives at ~2004 ms
  one conn each: the fast assets arrive at 3-7 ms
```

HTTP/1.1 has no way to say *"this response is for request 4"*. So responses come
back in request order, and one slow response holds up everything behind it.

**`headers.py`** counts the other tax: 80 requests × 805 bytes of headers =
64,320 bytes, of which 1,600 bytes are the only thing that changes. 97.5% of
what you upload is a byte-for-byte repeat.

**`framing.py`** sends one byte stream that two conformant parsers read as one
request or as two. RFC 2616 §4.4 said *"the latter MUST be ignored"*; RFC 9112
§6.3, twenty-three years later, says reject it and close the connection. That
is request smuggling, and it is the sound of Postel's law losing an argument.

## Hour 4 — HTTP/2 (RFC 9113, June 2022; was RFC 7540, May 2015)

```bash
tools/lab.sh h2
python3 04-http2/hpack_mini.py                       # RFC 7541 test vectors
python3 04-http2/h2_client.py --port 8020 --path /
python3 04-http2/h2_client.py --port 8443 --tls --path /
python3 04-http2/h2_client.py --port 8020 --multiplex --slow 2
```

`hpack_mini.py` implements RFC 7541 in about 150 lines of logic — prefix
integers, the 61-entry static table, the dynamic table, canonical Huffman — and
checks itself against the RFC's own Appendix C vectors *and* against the `hpack`
package. On a realistic request header set:

```
  HTTP/1.1 text            174 bytes
  HPACK, first time         79 bytes   (55% smaller)
  HPACK, second time         6 bytes   (97% smaller)  <- the dynamic table
```

`h2_client.py` speaks HTTP/2 by hand and prints every frame header as hex, so
the 9 bytes of `00 01 07 00 00 00 00 00 01` are visible as
*length 263, type DATA, no flags, stream 1*. Then `--multiplex` runs the same
six requests as `hol.py`, on one connection:

```
  stream 3   /style.css      done at      4.9 ms
  stream 11  /hero.png       done at      7.8 ms
  stream 1   /big.txt?delay=2  done at 2005.9 ms
```

Same six requests. Same one TCP connection. The difference is 31 bits of stream
identifier on every frame.

> Two notes on the server, both bugs I actually shipped and then found.
>
> The first version of `h2_server.py` handled requests inline in the read loop,
> and the multiplexing demo produced *exactly* the HTTP/1.1 numbers — all six
> streams at 2005 ms. The framing layer gave permission to interleave; the
> application did not take it.
>
> The second was worse, because it was intermittent. `flush()` took the lock,
> called `data_to_send()`, released the lock, and *then* did the blocking
> `sendall()`. Two threads could each grab a buffer and then race to write them,
> so frames reached the wire in a different order than the HPACK encoder had
> produced them in — and the client's dynamic table diverged from the server's:
>
> ```
> IndexError: index 75 is not in either table
> ```
>
> It looks exactly like a bug in the decoder. It is not; `hpack_mini.py` and the
> reference `hpack` package fail identically on those bytes, which is how you
> know. Serialising the *encoder* is not enough — you have to serialise the
> *write*. The fix queues the bytes to a single writer thread while the lock is
> still held. Both comments are still in the file, because they are the more
> useful half of the lesson.
>
> It surfaced under `tools/stall_tcp.py` and almost never without it, because a
> blocking `sendall()` into a stalled connection widens the race window from
> microseconds to 300 ms. Concurrency bugs are latency-sensitive; that is why
> they find production and not your laptop.

## Hour 5 — QUIC and HTTP/3 (RFC 9000 May 2021, RFC 9114 June 2022)

```bash
tools/lab.sh h3
python3 05-http3/h3_client.py --port 4433 --multiplex
python3 05-http3/handshake_race.py --rtt 150
```

**Head-of-line blocking, the part HTTP/2 could not fix.** RFC 9114 §1.1:
*"a lost or reordered packet causes all active transactions to experience a
stall regardless of whether that transaction was directly impacted by the lost
packet."* Two runs, same six requests:

```
  [a] HTTP/2 over TCP, one 300 ms stall in the byte stream
      /app.js      7.5 ms      <- got through before the hole
      /style.css 308.5 ms
      /hero.png  308.3 ms      <- all of these were ready in milliseconds
      /icon.png  308.3 ms
      /logo.png  308.4 ms

  [b] HTTP/3 over QUIC, 18 datagrams actually dropped (5%)
      /style.css   4.5 ms
      /app.js      5.4 ms
      /logo.png    6.7 ms
      /icon.png    7.8 ms
      /hero.png   11.0 ms
      /big.txt    78.2 ms      <- only the stream that lost packets waited
```

Be precise about what these two runs are: the TCP side delays one chunk of the
byte stream by 300 ms, which is the *shape* a lost segment produces; the QUIC
side deletes real datagrams and makes QUIC's own loss detection (RFC 9002) find
them. Different perturbations. The point is not the millisecond counts, it is
that in [a] the delay reaches streams that lost nothing, and in [b] it does not.

Run [a] a few times — `run_all.sh` does it three times on purpose. Which of the
small files sneak through before the 3,000-byte stall point and which get caught
behind it changes every run, because it depends on the order the server's threads
happened to write into one shared byte stream. That is not noise in the
experiment; it is the complaint. Under HTTP/2 the blast radius of one lost
segment is "whichever streams had bytes behind it", and you do not get to choose.
Under HTTP/3 the blast radius is exactly one stream, every time.

**Round trips before the first byte**, measured at 150 ms RTT:

```
  TCP + TLS 1.3 + h2 (new connection)         456.6 ms      3.0 RTT
  QUIC + HTTP/3 (new connection, 1-RTT)       319.8 ms      2.1 RTT
  QUIC + HTTP/3 (0-RTT, request in flight 1)  161.7 ms      1.1 RTT
```

TCP spends a whole round trip agreeing to exist before TLS is allowed to start.
QUIC merges the two handshakes (RFC 9001 §2.1). 0-RTT puts the request in the
very first flight — and RFC 9001 §9.2 is blunt about the price: early data is
replayable, so a 0-RTT request must be one you would not mind serving twice.

---

## Homework

1. **Break the 2-connection rule and find where it stops helping.** Extend
   `fetch_page.py` to N connections and plot wall time against N at 150 ms RTT
   for 6, 20 and 60 assets. Find the knee. Then explain the knee — it is not
   where you think, and `ss -ti` will tell you (look at `cwnd`).

2. **Make the 304 lie.** `server11.py` builds its ETag from the file's bytes.
   Change it to use the mtime instead, then modify a file twice inside one
   second. You have just reproduced the bug that made ETags exist. Then read
   RFC 9110 §8.8.1 on strong versus weak validators and decide which you had.

3. **Decode a HEADERS frame with a pencil.** Run `h2_client.py` with a long
   cookie, take the hex of the HPACK block, and decode the first three field
   lines by hand against RFC 7541 §6 before you let `hpack_mini.py` do it. Then
   send the same request twice and explain why the second block is 6 bytes.

4. **Find the head-of-line blocking in QPACK.** RFC 9204 exists because HPACK's
   dynamic table assumes total ordering, which QUIC does not give it. Set
   `SETTINGS_QPACK_BLOCKED_STREAMS` to 0 and then to 16 in `h3_server.py`, and
   work out what the encoder is allowed to do differently in each case.

5. **Block UDP 443 and watch the fallback.** `iptables -A OUTPUT -p udp
   --dport 4433 -j DROP`, then run `h3_client.py` and time how long it takes to
   give up. Now read RFC 9308 §2 on the 3–5% of networks that block UDP, and
   decide what your own timeout should be.

## What this repo does not cover

TLS itself (Session 2 did handshakes; the certificate here is self-signed and
verification is off), HTTP/2 priority and `PRIORITY_UPDATE` (RFC 9218), server
push (removed from Chrome in version 106, September 2022 — the replacement is
`103 Early Hints`), QUIC connection migration, and the whole of caching beyond
`ETag`/`Vary`. All are good places to go next.
