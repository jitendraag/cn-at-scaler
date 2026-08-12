# cn-at-scaler

Small, self-contained C socket programs for exploring basic TCP server
patterns and signal behavior. Each file is deliberately minimal — no error
handling, no CLI flags — just enough code to demonstrate one concept.

All servers listen on port **2026**.

## Echo servers

| File | Behavior |
|---|---|
| `echo_server.c` | Accepts a connection, echoes a single read back, closes it. Repeats. |
| `echo_server_persistent.c` | Same, but keeps the connection open and keeps echoing until the client closes it. |
| `echo_server_fork.c` | Same as the persistent server, but `fork()`s a child process per connection so multiple clients can be handled concurrently. |

Build and run any of them, e.g.:

```sh
gcc -o echo_server_fork echo_server_fork.c
./echo_server_fork
```

Then connect with `nc localhost 2026`.

## SIGPIPE demo

Demonstrates a process dying from an unhandled `SIGPIPE` when it writes to a
socket the peer has already reset.

- `sigpipe_server.c` — reads once from a client, sleeps a second, then writes
  twice. If the peer has reset the connection by then, the first `write()`
  raises `SIGPIPE`, which kills the process by default.
- `sigpipe_client.c` — connects, sends a few bytes, then force-closes the
  socket with `SO_LINGER{1,0}` (sends a TCP `RST` instead of a normal `FIN`).
- `sigpipe_client_dns.c` — same client, but resolves the server host with
  `gethostbyname()` instead of hardcoding an IP.
- `sigpipe_client_getaddrinfo.c` — same client, using `getaddrinfo()` (the
  modern, protocol-independent replacement for `gethostbyname()`).

```sh
gcc -o sigpipe_server sigpipe_server.c
gcc -o sigpipe_client sigpipe_client.c
./sigpipe_server &
./sigpipe_client
wait
echo $?   # 141 = 128 + SIGPIPE(13)
```

## Notes

This code intentionally skips error handling and return-value checks to stay
short and readable — it's meant for demonstrating networking/signal concepts,
not as production-quality code.
