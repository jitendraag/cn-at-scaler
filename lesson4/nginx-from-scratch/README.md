# nginx-from-scratch

Companion code for **CN & Scaler, Session 4 — nginx**.

Seven small programs that each do one thing nginx does, plus one `nginx.conf`
that does all of them for real, plus [`NGINX-TOUR.md`](NGINX-TOUR.md) — a
guided tour of the actual nginx source with pinned file:line references.

The order is the history. Read them in order and you will have rebuilt the
1994 → 2004 evolution of the web server with your own hands.

```
01-fork/       fork() per client                    Apache 1.3, 1995
02-thread/     pthread per client                   Apache 2.0 worker, 1999
03-select/     one thread, select()                 ...and the 1024 wall
04-epoll/      one thread, epoll()                  nginx, 2004
05-sendfile/   read vs mmap vs sendfile             the copies, counted
06-fastcgi/    the FastCGI wire protocol, both ends CGI without the fork
07-nginx/      one nginx.conf, five demos, real     all of the above at once
```

## Build and run

```bash
make                     # everything; needs gcc, pthreads, Linux (epoll)
ulimit -n 65536          # you will need this
```

Every server takes a port as `argv[1]` and has a sensible default.

```bash
make run-fork            # :8001   then: ps -o pid,ppid,rss,vsz -C forkd
make run-thread          # :8002   then: ps -o pid,nlwp,rss,vsz -p $(pgrep threadd)
make run-select          # :8003   then: tools/flood.sh 8003 1100
make run-epoll           # :8004   then: tools/flood.sh 8004 5000
make run-sendfile        # :8005   needs `make bigfile` first
make run-fcgi            # :9000   the FastCGI responder
```

## The five minutes that matter in each one

**01-fork** — `curl` it, then watch `ps`. One OS process per *in-flight*
request. Hold a connection open with `telnet` and the process stays. Comment
out the `SIGCHLD` handler and meet zombies.

**02-thread** — it prints its own default stack size at startup: **8 MiB**.
Ten thousand threads is 80 GB of address space. `STACK=65536 ./threadd` shrinks
it and you can watch VSZ collapse. A Go goroutine starts at 2 KiB, which is why
this model came back.

**03-select** — `FD_SETSIZE` is **1024**, hard-coded in a header, and
`ulimit -n 65536` does not move it. There is a guard in the code so you get a
clean message instead of a stack smash; delete the guard once, on purpose, so
you recognise the crash for the rest of your life.

```
$ tools/flood.sh 8003 1100
[pid 2219] fd 1024 >= FD_SETSIZE (1024). select() CANNOT watch this
           descriptor. Closing. This is the wall.
```

**04-epoll** — the same flood at 5000 does nothing at all. Then read the
comment about **stale events**: `epoll_wait()` returns a batch, handling event 1
can free the connection event 7 points at, and nginx's answer is to steal the
low bit of the pointer as a generation flag. Every event-loop author writes this
bug exactly once.

**05-sendfile** — read the honesty note below before you demo this.

**06-fastcgi** — `fcgi_client` hexdumps every byte it puts on the wire.
`01 01 00 01 00 08 00 00` is the first eight bytes of every FastCGI connection
on earth. The **empty record** is the end-of-stream delimiter and there is no
other one.

**07-nginx** — all of it, for real, with the config commented line by line.

## Being honest about the sendfile demo

```
mode=read      wall  37.4 ms | sys 37.3 | 2048 syscalls
mode=mmap      wall  23.3 ms | sys 23.1 |    4 syscalls
mode=sendfile  wall  33.2 ms | sys 32.3 |    1 syscall
```

**On loopback, `sendfile` does not win on wall-clock time**, and students will
run this and see it. There is no NIC and no DMA — the kernel copies into the
receiver's buffer either way — and `curl` on the same box is competing for the
same CPU.

What is real and visible on any machine: **2048 syscalls become 1**, and 64 MB
never enters your address space. The wall-clock win needs a real NIC with
scatter-gather DMA, and it shows up as *headroom under concurrency*, not as a
faster single transfer. Demo it, show the flat number, and explain why — that
lesson about benchmarks is worth as much as the lesson about `sendfile`.

## The nginx demos

```bash
cd 07-nginx
mkdir -p logs temp
cp /etc/nginx/mime.types .
nginx -p $PWD -c $PWD/nginx.conf          # daemon off; is in the config
```

Start `01-fork/forkd 8001`, `04-epoll/epolld 8004` and
`06-fastcgi/fcgi_responder 9000` alongside — nginx proxies to them.

| port | demo | try |
|---|---|---|
| 8080 | static + `sendfile` + `open_file_cache` | `curl -i :8080/index.html` |
| 8081 | `location` precedence | `curl :8081/exact` `:8081/images/a.php` `:8081/other/a.php` `:8081/anything` |
| 8082 | reverse proxy + cache + weighted LB | `curl -i :8082/` twice, read `X-Cache-Status` |
| 8083 | `fastcgi_pass` → our own 200-line responder | `curl :8083/hello?a=1` |
| 8084 | `try_files` fallbacks | `curl :8084/does-not-exist` |

Two demos that land every time:

**Routing precedence.** Make them predict all four answers before you press
enter. nginx checks locations in a fixed order that has nothing to do with the
order you wrote them in.

```
/exact          -> 1: exact match
/images/a.php   -> 2: prefix, regex skipped
/other/a.php    -> 3: regex
/anything       -> 4: catch-all prefix
```

**Weighted round robin, measured.** The config weights `:8004` at 3 and `:8001`
at 1, and the custom `log_format` shows `$upstream_addr`:

```bash
for i in $(seq 24); do curl -s "localhost:8082/x-$i-$RANDOM" -o /dev/null; done
grep -o 'upstream=[0-9.:]*' logs/access.log | sort | uniq -c
#   6 upstream=127.0.0.1:8001
#  18 upstream=127.0.0.1:8004        <- exactly 3:1
```

The same log line also shows `rt=2.001 urt=2.000` — request time minus upstream
time is what nginx itself cost you. One millisecond. When that gap is *not*
tiny, you have found your problem.

## Then read the real thing

[`NGINX-TOUR.md`](NGINX-TOUR.md) — ten stops in the nginx source, pinned against
1.31.5, each one next to whichever program in this repo does the same thing:

process model · the event loop · accept and the accept mutex · epoll and stale
events · the HTTP parser as a resumable DFA · phases and the location tree ·
the sendfile decision · the cache LRU · smooth weighted round robin ·
the FastCGI record state machine

Plus: how to read any nginx module in ten minutes, and five homework problems.

## Requirements

Linux (epoll, sendfile, accept4), gcc or clang, `make`, python3 for
`tools/flood.sh`, and `nginx` for the `07-nginx` demos. Everything else is
libc and pthreads.

Nothing here is production code. It is deliberately short, deliberately
single-purpose, and it ignores error paths that a real server cannot ignore.
That is the point — nginx handles all of them, which is why nginx is 200,000
lines and this is 1,200.
