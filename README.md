# cn-at-scaler

Small, self-contained C socket programs for exploring basic TCP server
patterns and signal behavior. Each file is deliberately minimal — no error
handling, no CLI flags — just enough code to demonstrate one concept.

All servers listen on port **2026**. Source files live in `lesson1/`, numbered
in demo order.

## Echo servers

| File | Behavior |
|---|---|
| `01_echo_server.c` | Accepts a connection, echoes a single read back, closes it. Repeats. |
| `02_echo_server_persistent.c` | Same, but keeps the connection open and keeps echoing until the client closes it. |
| `03_echo_server_fork.c` | Same as the persistent server, but `fork()`s a child process per connection so multiple clients can be handled concurrently. |

Build and run any of them, e.g.:

```sh
cd lesson1
gcc -o 03_echo_server_fork 03_echo_server_fork.c
./03_echo_server_fork
```

Then connect with `nc localhost 2026`.

## SIGPIPE demo

Demonstrates a process dying from an unhandled `SIGPIPE` when it writes to a
socket the peer has already reset.

- `04_sigpipe_server.c` — reads once from a client, sleeps a second, then
  writes twice. If the peer has reset the connection by then, the first
  `write()` raises `SIGPIPE`, which kills the process by default.
- `05_sigpipe_client.c` — connects, sends a few bytes, then force-closes the
  socket with `SO_LINGER{1,0}` (sends a TCP `RST` instead of a normal `FIN`).
- `06_sigpipe_client_dns.c` — same client, but resolves the server host with
  `gethostbyname()` instead of hardcoding an IP.
- `07_sigpipe_client_getaddrinfo.c` — same client, using `getaddrinfo()` (the
  modern, protocol-independent replacement for `gethostbyname()`).

```sh
cd lesson1
gcc -o 04_sigpipe_server 04_sigpipe_server.c
gcc -o 05_sigpipe_client 05_sigpipe_client.c
./04_sigpipe_server &
./05_sigpipe_client
wait
echo $?   # 141 = 128 + SIGPIPE(13)
```

## Encoding samples

Small standalone programs demonstrating common wire-encoding schemes.

| File | Behavior |
|---|---|
| `08_bcd.c` | Packs decimal digits 2-per-byte (BCD), pads an odd trailing digit with nibble `0xF`, decodes back. |
| `09_base64.c` | Standard base64 encode/decode using the RFC 4648 alphabet. |
| `10_tlv.c` | Generic 1-byte type / 1-byte length / value encode and decode. |
| `11_asn1_der.c` | Minimal DER encoder: an `INTEGER` (tag `0x02`, showing the leading-`0x00` rule when the high bit is set) nested inside a `SEQUENCE` (tag `0x30`). |

```sh
cd lesson1
gcc -o 08_bcd 08_bcd.c && ./08_bcd
```

## Notes

This code intentionally skips error handling and return-value checks to stay
short and readable — it's meant for demonstrating networking/signal concepts,
not as production-quality code.
