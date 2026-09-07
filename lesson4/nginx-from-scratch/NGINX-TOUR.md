# Reading nginx: a guided tour

Pinned against **nginx 1.31.5**, commit `231a60ee`, `github.com/nginx/nginx`.

```bash
git clone --depth 1 https://github.com/nginx/nginx.git
cd nginx && git log -1 --oneline
```

**Line numbers drift. Function names do not.** Every stop below gives you a
function name first and a line number second. If the line is wrong, do this:

```bash
grep -rn "^ngx_epoll_process_events" src/
```

nginx's style puts the return type on its own line, so `^function_name(` finds
the definition and nothing else. That one habit makes the whole tree navigable.

---

## Stop 0 — the shape of the tree, in two minutes

```
src/core/    ngx_string, ngx_array, ngx_list, ngx_hash, ngx_rbtree, ngx_queue,
             ngx_palloc, ngx_buf, ngx_conf_file, ngx_cycle, ngx_connection
             ^ nginx's standard library. It has its own everything, because in
               1999 you could not portably rely on anyone else's.
src/event/   the event loop and the poll-mechanism modules
   modules/  ngx_epoll_module.c, ngx_kqueue_module.c, ngx_select_module.c,
             ngx_poll_module.c, ngx_devpoll_module.c, ngx_eventport_module.c
             ^ six ways to wait. Same interface. Pick one at ./configure time.
src/http/    the HTTP state machine, the phase engine, the upstream framework
   modules/  every directive you have ever typed: proxy, fastcgi, gzip, rewrite,
             ssl, headers, autoindex, try_files, ...
src/os/unix/ the syscall layer: sendfile per-OS, process spawning, shared mem
src/stream/  the same architecture again, for raw TCP/UDP (nginx as an L4 LB)
src/mail/    the same architecture a third time, for IMAP/POP3/SMTP proxying
```

Three protocol trees, one core. When you have read `src/http/` you can read
`src/stream/` in an afternoon. **That repetition is the argument for the
architecture** — say it out loud in class.

Two files worth opening before any of the code:

- `src/core/ngx_queue.h` — an intrusive doubly-linked list, ~50 lines of macros.
  The LRU in the cache, the posted-events list and the timer-adjacent code all
  ride on this.
- `src/core/ngx_palloc.h` — the memory pool. **nginx does not free per-request
  memory.** It allocates from a pool attached to the request and destroys the
  whole pool at the end. No refcounting, no leak class, no free() on the hot
  path. This is why nginx code has almost no cleanup branches, and it is the
  single biggest reason it reads so cleanly.

---

## Stop 1 — the process model: fork once, at startup

| file | function | ~line |
|---|---|---|
| `src/os/unix/ngx_process_cycle.c` | `ngx_master_process_cycle()` | 74 |
| `src/os/unix/ngx_process_cycle.c` | `ngx_start_worker_processes()` | 358 |
| `src/os/unix/ngx_process_cycle.c` | `ngx_worker_process_cycle()` | 729 |
| `src/os/unix/ngx_process.c` | `ngx_spawn_process()` | 87 |

The master forks N workers and then does nothing but handle signals. It never
touches a connection. Workers never fork.

Compare to `01-fork/forkd.c` in this repo, which forks per connection. **Same
syscall. The only difference is how often you call it**, and that difference is
the entire 1994→2004 story.

Run this while nginx serves traffic:

```bash
watch -n0.2 'ps -o pid,ppid,etime,args -C nginx'
```

You will see: 1 master, N workers, 1 cache manager, 1 cache loader. The count
does not move under load. Now do the same for `01-fork/forkd` and watch it move.

**Ask the class:** the master runs as root (to bind :80) and the workers drop to
`nginx`. Why does that split exist, and what does it buy you the day a worker is
compromised?

---

## Stop 2 — the loop every worker runs forever

| file | function | ~line |
|---|---|---|
| `src/event/ngx_event.c` | `ngx_process_events_and_timers()` | 195 |
| `src/event/ngx_event.c` | `ngx_event_process_init()` | 636 |

The whole of nginx, in the order it happens:

```c
timer = ngx_event_find_timer();          /* when is the next deadline? */
ngx_process_events(cycle, timer, flags); /* -> epoll_wait(), sleeps here */
ngx_event_process_posted(cycle, &ngx_posted_accept_events);
ngx_shmtx_unlock(&ngx_accept_mutex);     /* let a sibling accept */
ngx_event_expire_timers();               /* fire everything that timed out */
ngx_event_process_posted(cycle, &ngx_posted_events);
```

Six lines. Read them until they are boring. Everything else in `src/http/` is a
callback reached from line 3 or line 6.

Two things to notice:

1. **The timer is an argument to the sleep.** nginx never polls for timeouts —
   it computes the nearest deadline and sleeps exactly that long. Timeouts cost
   nothing when nothing is timing out. The timer tree is an rbtree
   (`ngx_event_timer.c`), so "nearest deadline" is a leftmost-node lookup.
2. **Posted events.** Handlers do not run inside the epoll loop; they get queued
   and drained after. That is how nginx avoids recursion depth and how it keeps
   accept events ahead of read events.

### The accept mutex, and why it is off now

`ngx_process_events_and_timers()` ~L224:

```c
if (ngx_use_accept_mutex) {
    if (ngx_accept_disabled > 0) { ngx_accept_disabled--; }
    else if (ngx_trylock_accept_mutex(cycle) == NGX_ERROR) { return; }
}
```

And in `src/event/ngx_event_accept.c` ~L139:

```c
ngx_accept_disabled = ngx_cycle->connection_n / 8 - ngx_cycle->free_connection_n;
```

Read that as English: *"once I am using more than 7/8 of my connection slots,
stop competing for new connections and let my siblings take them."* Load
balancing between workers, in one line of arithmetic, with no coordinator.

`accept_mutex` defaults to **off** since 1.11.3, because `EPOLLEXCLUSIVE`
(Linux 4.5+) and `SO_REUSEPORT` let the kernel do the fan-out. The mutex was a
userspace fix for a kernel problem, and the kernel fixed it. **Ask the class:**
what is the cost of the mutex when it is on, and what is the cost of
`SO_REUSEPORT` when a worker is slow?

---

## Stop 3 — accept

| file | function | ~line |
|---|---|---|
| `src/event/ngx_event_accept.c` | `ngx_event_accept()` | 21 |

```c
do {
    s = accept4(lc->fd, &sa.sockaddr, &socklen, SOCK_NONBLOCK);  /* ~L61 */
    ...
} while (ev->available);
```

`accept4()` with `SOCK_NONBLOCK` instead of `accept()` + `fcntl()` — one syscall
instead of two, on a path that runs once per connection. That is the level of
parsimony to expect from this codebase.

`ev->available` is `multi_accept`: drain the whole accept queue in one wakeup, or
take one and go back to the loop. Both are defensible; find the trade-off before
you read on. (Hint: what happens to the *other* connections' latency?)

`04-epoll/epolld.c` in this repo does the same loop-until-EAGAIN.

---

## Stop 4 — epoll, and the stale-event bug you will otherwise write yourself

| file | function | ~line |
|---|---|---|
| `src/event/modules/ngx_epoll_module.c` | `ngx_epoll_init()` | 323 |
| `src/event/modules/ngx_epoll_module.c` | `ngx_epoll_add_event()` | 579 |
| `src/event/modules/ngx_epoll_module.c` | `ngx_epoll_process_events()` | 784 |

Compare side by side with `src/event/modules/ngx_select_module.c`
`ngx_select_process_events()` (~L222). Same function signature, same job. select
rebuilds the whole fd_set every iteration; epoll does not. **That is the entire
difference, and it is worth showing on one screen.**

The five lines to stop on, in `ngx_epoll_process_events()` ~L839:

```c
c = event_list[i].data.ptr;

instance = (uintptr_t) c & 1;
c = (ngx_connection_t *) ((uintptr_t) c & (uintptr_t) ~1);

if (c->fd == -1 || rev->instance != instance) {
    /* the stale event from a file descriptor that was just closed
       in this iteration */
    continue;
}
```

`epoll_wait()` returns a **batch**. Handling event 1 can close the connection
that event 7 points at — and if a new client arrives on the recycled fd in
between, you will deliver event 7 to the wrong person. nginx steals the low bit
of the connection pointer (structs are aligned, so it is always zero) as a
generation flag and flips it on reuse.

This is the bug every event-loop author writes once. `04-epoll/epolld.c` solves
it the readable way with an explicit generation counter; read that first, then
this.

**Ask the class:** why is the low bit always free? What breaks if someone
allocates a `ngx_connection_t` at an odd address?

---

## Stop 5 — parsing HTTP without a single allocation

| file | function | ~line |
|---|---|---|
| `src/http/ngx_http_request.c` | `ngx_http_init_connection()` | 211 |
| `src/http/ngx_http_request.c` | `ngx_http_wait_request_handler()` | 377 |
| `src/http/ngx_http_request.c` | `ngx_http_process_request_line()` | 1115 |
| `src/http/ngx_http_request.c` | `ngx_http_process_request_headers()` | 1401 |
| `src/http/ngx_http_request.c` | `ngx_http_alloc_large_header_buffer()` | 1657 |
| `src/http/ngx_http_parse.c` | `ngx_http_parse_request_line()` | 108 |
| `src/http/ngx_http_parse.c` | `ngx_http_parse_header_line()` | 871 |

Open `ngx_http_parse_request_line()` and look at the first 30 lines: a 27-state
enum and a `for` loop with a `switch`. No regex, no `strtok`, no `substr`, no
allocation. It is a hand-written DFA over one byte at a time, and it can be
suspended and resumed mid-byte — which is the whole point, because the request
line may arrive in three TCP segments.

`r->state` survives between calls. **That is what "non-blocking" costs you at
the source level**: every parser has to be a resumable state machine, because
you can be interrupted anywhere. Compare with a thread-per-connection server,
where `read()` until you see `\r\n\r\n` is fine because blocking is free.

Method dispatch, ~L172, is worth a laugh and then a think:

```c
case 3:
    if (ngx_str3_cmp(m, 'G', 'E', 'T', ' ')) { r->method = NGX_HTTP_GET; break; }
```

Switch on length first, then compare 4 bytes as a single word. No `strcmp`.

`ngx_http_alloc_large_header_buffer()` is where `large_client_header_buffers`
lives, and where a request that is too big becomes **414** or **400**. It also
has to *relocate* every pointer already parsed into the old buffer — read the
"the client fills up the buffer" comment and see what a zero-copy parser costs
you when the buffer has to move.

**Ask the class:** what is the maximum size of a URL nginx will accept, and
where exactly is that number?

---

## Stop 6 — routing: phases and the location tree

| file | function | ~line |
|---|---|---|
| `src/http/ngx_http_core_module.c` | `ngx_http_core_run_phases()` | 894 |
| `src/http/ngx_http_core_module.c` | `ngx_http_core_find_config_phase()` | 980 |
| `src/http/ngx_http_core_module.c` | `ngx_http_core_content_phase()` | 1302 |
| `src/http/ngx_http_core_module.c` | `ngx_http_core_find_location()` | 1446 |
| `src/http/ngx_http_core_module.c` | `ngx_http_core_find_static_location()` | 1542 |
| `src/http/ngx_http_core_module.h` | `ngx_http_phases` enum | 111 |

The whole request pipeline is eleven phases (`ngx_http_core_module.h` ~L111):

```
POST_READ → SERVER_REWRITE → FIND_CONFIG → REWRITE → POST_REWRITE
   → PREACCESS → ACCESS → POST_ACCESS → PRECONTENT → CONTENT → LOG
```

and the engine that runs them is four lines (~L904):

```c
while (ph[r->phase_handler].checker) {
    rc = ph[r->phase_handler].checker(r, &ph[r->phase_handler]);
    if (rc == NGX_OK) { return; }     /* yield: we are waiting on I/O */
}
```

`return` here does not mean "done", it means **"suspended"**. The request will
resume in a later loop iteration when its event fires, re-entering this same
`while` at the phase it left off. A coroutine, hand-rolled, in C, in 1999.

Every module you configure is a handler registered into one of these phases:
`limit_req` in PREACCESS, `auth_basic` in ACCESS, `try_files` in PRECONTENT,
`proxy_pass` / `fastcgi_pass` / static in CONTENT. **`grep -rn "NGX_HTTP_.*_PHASE\].handlers" src/http/modules/`** prints the map of which module runs when —
run it in class, it is a one-line answer to "why did my directive not fire".

`ngx_http_core_find_static_location()` is the prefix-location matcher: a
**ternary search tree walked one URI segment at a time**, built at config-parse
time. `left`/`right` on byte comparison, `tree` to descend into the next segment
when the match is `inclusive`. That is why 500 prefix locations cost nothing and
500 regex locations cost you a linear scan per request.

Demo it live with `07-nginx/nginx.conf` port 8081, and make them predict the
answers before you press enter:

| request | wins | why |
|---|---|---|
| `/exact` | `location = /exact` | exact beats everything, search stops |
| `/images/a.php` | `location ^~ /images/` | `^~` suppresses the regex search |
| `/other/a.php` | `location ~ \.php$` | regex beats a shorter prefix |
| `/anything` | `location /` | no regex matched, longest prefix wins |

---

## Stop 7 — sendfile

| file | function | ~line |
|---|---|---|
| `src/http/modules/ngx_http_static_module.c` | `ngx_http_static_handler()` | 49 |
| `src/os/unix/ngx_linux_sendfile_chain.c` | `ngx_linux_sendfile_chain()` | 50 |
| `src/os/unix/ngx_linux_sendfile_chain.c` | `ngx_linux_sendfile()` | 232 |

The decision is made far from the syscall. `ngx_http_static_handler()` ~L264:

```c
b->file_pos  = 0;
b->file_last = of.size;
b->in_file   = b->file_last ? 1 : 0;    /* <- the whole decision */
b->file->fd  = of.fd;
```

The handler never reads the file. It builds a buffer that says *"my contents are
in this fd, at this offset, this long"* and hands it to the output filter chain.
Everything downstream — gzip, ranges, ssl, the writer — either honours `in_file`
or forces the bytes into memory. **`sendfile on;` is a permission, not an
instruction.** Turn on `gzip` for the same location and `in_file` cannot survive:
the gzip filter has to see the bytes.

In `ngx_linux_sendfile_chain()` ~L95, the `TCP_CORK` block:

```c
/* set TCP_CORK if there is a header before a file */
if (c->tcp_nopush == NGX_TCP_NOPUSH_UNSET && header.count != 0
    && cl && cl->buf->in_file) { ... ngx_tcp_nopush(c->fd) ... }
```

Headers go out with `writev()`, body with `sendfile()`. Without the cork those
are two segments and you have wasted one. Note the comment two lines further
down: *"the TCP_CORK and TCP_NODELAY are mutually exclusive"* — nginx explicitly
un-sets NODELAY, corks, sends, and puts it back.

And `ngx_linux_sendfile()` ~L261 is just:

```c
n = sendfile(c->fd, file->file->fd, &offset, size);
```

with `EINTR` retry and `EAGAIN` handling. **That is it.** Nine hundred lines of
buffer-chain machinery exist so that this one line can be reached with the right
arguments.

### What you will actually measure — read this before you demo

Run `05-sendfile/sendfiled` and be honest with the class about the result:

```
mode=read      wall  37.4 ms | sys 37.3 | 2048 syscalls
mode=mmap      wall  23.3 ms | sys 23.1 |    4 syscalls
mode=sendfile  wall  33.2 ms | sys 32.3 |    1 syscall
```

**On loopback, sendfile does not win on wall-clock time.** There is no NIC and
no DMA — the kernel memcpy's into the receiver's buffer either way — and `curl`
on the same box is competing for the same CPU. What you can see on any machine
is the syscall count: **2048 → 1**, and the fact that 64 MB never entered your
address space.

Demoing this and pretending the wall-clock number proves the point is how
students learn to distrust benchmarks. Demo it and explain why the number is
flat. The win is real on a real NIC with scatter-gather DMA and checksum
offload, at 10,000 concurrent clients, where the CPU you did not spend copying
is the CPU you spend on somebody else's request.

---

## Stop 8 — the cache is an LRU, and the LRU is one line

| file | function | ~line |
|---|---|---|
| `src/http/ngx_http_file_cache.c` | `ngx_http_file_cache_open()` | 265 |
| `src/http/ngx_http_file_cache.c` | `ngx_http_file_cache_lookup()` | 1029 |
| `src/http/ngx_http_file_cache.c` | `ngx_http_file_cache_update()` | 1418 |
| `src/http/ngx_http_file_cache.c` | `ngx_http_file_cache_forced_expire()` | 1761 |
| `src/http/ngx_http_file_cache.c` | `ngx_http_file_cache_expire()` | 1860 |

Two data structures in shared memory, both pointing at the same nodes:

- an **rbtree** keyed on the MD5 of `proxy_cache_key` — that is the lookup;
- an **`ngx_queue_t`** in recency order — that is the LRU.

Eviction, ~L1900:

```c
q   = ngx_queue_last(&cache->sh->queue);
fcn = ngx_queue_data(q, ngx_http_file_cache_node_t, queue);
wait = fcn->expire - now;
if (wait > 0) { ... break; }
if (fcn->count == 0) { ngx_http_file_cache_delete(cache, q, name); }
```

*Take the tail. Is it old? Is nobody using it? Delete it.* That is the whole
eviction policy, and the `count == 0` check is why an object being streamed to a
client right now cannot be evicted out from under it.

Note what `keys_zone=demo:10m` actually sizes: **the index, not the data.** Ten
megabytes of shared memory holding rbtree nodes and queue links, roughly 8000
keys per MB. The bodies are files on disk under `levels=1:2` (two directory
levels, so no single directory holds a million entries and destroys your
filesystem's lookup time).

**Ask the class:** `inactive=60s` and `proxy_cache_valid 10s` are both in the
config on port 8082. What does each one do, and which one wins?

---

## Stop 9 — upstreams: weighted round robin in ten lines

| file | function | ~line |
|---|---|---|
| `src/http/ngx_http_upstream_round_robin.c` | `ngx_http_upstream_get_round_robin_peer()` | 697 |
| `src/http/ngx_http_upstream_round_robin.c` | `ngx_http_upstream_get_peer()` | 811 |
| `src/http/ngx_http_upstream_round_robin.c` | `ngx_http_upstream_free_round_robin_peer()` | 1008 |
| `src/http/ngx_http_upstream.c` | the whole upstream framework | — |

From `ngx_http_upstream_get_peer()` ~L884:

```c
peer->current_weight += peer->effective_weight;
total                += peer->effective_weight;

if (peer->effective_weight < peer->weight) { peer->effective_weight++; }

if (best == NULL || peer->current_weight > best->current_weight) {
    best = peer;
}
...
best->current_weight -= total;
```

This is **smooth** weighted round robin. Naive WRR with weights 3:1 emits
`a a a b`; this emits `a b a a`. Same ratio, no bursts at the origin. Prove it
live — the repo's `nginx.conf` weights `8004` at 3 and `8001` at 1:

```bash
for i in $(seq 24); do curl -s "localhost:8082/x-$i-$RANDOM" -o /dev/null; done
grep -o 'upstream=[0-9.:]*' logs/access.log | sort | uniq -c
#   6 upstream=127.0.0.1:8001
#  18 upstream=127.0.0.1:8004      <- exactly 3:1
```

`effective_weight` creeping back up (`if (effective_weight < weight) ++`) is
**passive health checking**: a peer that errors gets knocked down and earns its
traffic back over the next few requests. No probe traffic, no health-check
endpoint, no coordinator. Open-source nginx has no active health checks —
that is one of the things NGINX Plus sells.

**Ask the class:** three app servers, one of them 10x slower but still returning
200s. What does round robin do? What does `least_conn` do? Which of the two is
lying to you, and where does Little's Law come in? *(Session 3 called it: you
cannot configure your way past `concurrency = throughput × latency`.)*

---

## Stop 10 — FastCGI: framing, again

| file | function | ~line |
|---|---|---|
| `src/http/modules/ngx_http_fastcgi_module.c` | `ngx_http_fastcgi_create_request()` | 858 |
| `src/http/modules/ngx_http_fastcgi_module.c` | `ngx_http_fastcgi_process_header()` | 1735 |
| `src/http/modules/ngx_http_fastcgi_module.c` | `ngx_http_fastcgi_input_filter()` | 2219 |
| `src/http/modules/ngx_http_fastcgi_module.c` | `ngx_http_fastcgi_process_record()` | 2742 |

`ngx_http_fastcgi_process_record()` is another hand-written DFA, one byte at a
time, over the 8-byte record header:

```
st_version → st_type → st_request_id_hi → st_request_id_lo
  → st_content_length_hi → st_content_length_lo → st_padding_length
  → st_reserved → st_data
```

Two comments in it are worth reading aloud. At ~L2786:

```c
/* we support the single request per connection */
case ngx_http_fastcgi_st_request_id_lo:
    if (ch != 1) { ... return NGX_ERROR; }
```

FastCGI was *designed* for multiplexing — that is what `requestId` is for —
and nginx declines to use it, hardcoding id 1 and opening a connection per
request. **Ask the class why**, and let them argue. (Head-of-line blocking; a
slow response on a shared connection stalls the others; connection-per-request
plus `keepalive` in the upstream block gets you most of the win with none of the
coupling. It is the same argument that shows up again in HTTP/2 vs HTTP/3.)

And `create_request()` (~L858) is where nginx flattens your `fastcgi_param`
directives into the length-prefixed name/value encoding. It **computes the total
size first, allocates once, then fills** — no realloc on the request path.

Run `06-fastcgi/fcgi_client` next to this function and you have the same
protocol written twice: once as a parser, once as a generator. The client
hexdumps every byte it sends:

```
>> BEGIN_REQUEST
  0000  01 01 00 01 00 08 00 00  00 01 00 00 00 00 00 00
        ^v ^ty ^reqid ^clen ^pad
>> PARAMS  <- EMPTY = end of PARAMS
  0000  01 04 00 01 00 00 00 00
```

`01 01 00 01 00 08 00 00` is the first eight bytes of every FastCGI connection
on earth. Learn to spot it in a `tcpdump -X -i lo port 9000` and you can read a
capture without a dissector.

And there, at the end, is Session 2's closing idea one more time: **framing is
length or delimiter.** FastCGI uses a length in every record header *and* an
empty record as the end-of-stream delimiter. Both, at two different levels, in
one 20-page spec.

---

## How to read any nginx module in ten minutes

Every module — all 100+ of them — has the same four things. Open
`src/http/modules/ngx_http_static_module.c` (240 lines, the smallest real one)
and find them:

1. **`ngx_command_t []`** — the directives, their argument counts, and the
   setter for each. This is the config-file grammar, declared as data.
2. **`ngx_http_module_t`** — eight callbacks for creating and merging
   main/server/location configs. This is where `merge_loc_conf` decides what a
   `location` inherits from its `server`.
3. **`ngx_module_t`** — the glue that gets linked into `ngx_modules[]`.
4. **the handler(s)** — registered into a phase in the module's `init`:

```c
h = ngx_array_push(&cmcf->phases[NGX_HTTP_CONTENT_PHASE].handlers);
*h = ngx_http_static_handler;
```

Read those four in `static`, then in `try_files`, then in `fastcgi`. By the
third one the shape is automatic, and every remaining module is just a longer
version of the same file.

**The exercise that makes it stick:** pick any directive you have typed —
`sendfile`, `try_files`, `proxy_cache_valid` — and `grep -rn '"sendfile"' src/`.
You land in a `ngx_command_t` array. From there, the setter tells you which
struct field it writes; `grep` that field name and you land on the code that
reads it. Two greps from any directive to the code it controls. That is the
whole skill.

---

## Homework

1. **Break select, then fix it.** `tools/flood.sh 8003 1100` against
   `03-select/selectd`. Find the exact line where it gives up. Then delete the
   `FD_SETSIZE` guard and run it again — capture the crash, and explain in two
   sentences why `ulimit -n 65536` does not help. Then run the same flood at
   5000 against `04-epoll/epolld` and explain what changed.

2. **Find the sendfile decision.** In the nginx source, start from
   `sendfile on;` in a config and get to `sendfile(2)` in
   `ngx_linux_sendfile_chain.c` — writing down each function you pass through.
   Then add `gzip on;` to the same location, re-run, and show with `strace`
   that sendfile is gone. Explain which filter took it away.

3. **Speak FastCGI to something real.** Install php-fpm, point
   `06-fastcgi/fcgi_client` at it, and get a real PHP page back. Then
   `tcpdump -X -i lo port 9000` while nginx does the same request, and find
   `FCGI_BEGIN_REQUEST` by hand in the hex. Diff nginx's PARAMS list against
   the one our client sends — what does nginx send that we do not, and why?

4. **Make round robin lie to you.** Put `sleep(10)` in one of the three
   upstreams in `07-nginx/nginx.conf`, leave the weights at 3:1, and send 100
   requests. Show what happens to p99 under `round robin` and under
   `least_conn`. Then compute the concurrency Little's Law predicts and check
   it against `ss -tn | wc -l`.

5. **Read one module end to end.** Pick `ngx_http_try_files_module.c` (390
   lines). Write a one-page explanation of what happens to `try_files $uri
   $uri/ /index.html?$args` for a URI that does not exist — every stat, every
   allocation, and where the URI gets rewritten. Then explain why the *last*
   argument is the only one that is never tested.
