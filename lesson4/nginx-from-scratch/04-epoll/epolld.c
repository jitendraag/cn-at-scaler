/*
 * 04 — one thread, epoll().  Linux 2.5.44 (2002). This is nginx's shape.
 *
 *   ./epolld 8004
 *   ulimit -n 65536 && tools/flood.sh 8004 5000    # the run that killed 03
 *
 * Why this scales and select() does not
 * -------------------------------------
 *   select():  you hand the kernel the whole watch list on every call.
 *              Cost is O(watched).
 *   epoll():   the watch list lives in the kernel across calls. epoll_ctl()
 *              edits it; epoll_wait() returns only what fired.
 *              Cost is O(active).
 *
 * At 10,000 idle keep-alive connections with 10 active, select() does 10,000
 * units of work per tick and epoll does 10. That ratio is the whole reason
 * nginx exists.
 *
 * The two lines worth stealing
 * ----------------------------
 * 1. ev.data.ptr = c;
 *    epoll hands you back 64 bits of your own choosing. Do not put the fd
 *    there and then look it up in a table — put the connection pointer there
 *    and skip the lookup entirely. nginx does exactly this:
 *      src/event/modules/ngx_epoll_module.c  ngx_epoll_add_event()     (~L579)
 *
 * 2. The stale-event problem, and nginx's answer.
 *    epoll_wait() returns a batch. Handling event 1 can close the connection
 *    that event 7 refers to. By the time you reach event 7 the pointer is
 *    freed — or worse, reused for a brand new connection on a recycled fd,
 *    and you deliver a stale event to the wrong client.
 *    nginx steals the low bit of the pointer as an "instance" flag that flips
 *    every time a connection struct is reused, and checks it on the way out:
 *      instance = (uintptr_t) c & 1;
 *      c = (ngx_connection_t *) ((uintptr_t) c & (uintptr_t) ~1);
 *      if (c->fd == -1 || rev->instance != instance) { ... stale ... continue; }
 *      src/event/modules/ngx_epoll_module.c  ngx_epoll_process_events() (~L784)
 *    We do the same thing below with an explicit generation counter, which is
 *    the same idea with less pointer crime. Read nginx's version after this
 *    one and it will be obvious rather than terrifying.
 *
 * Level-triggered vs edge-triggered
 * ---------------------------------
 * We use level-triggered (no EPOLLET), which is what nginx uses by default.
 * Level: "this fd is readable" — reported every wait until you drain it.
 * Edge:  "this fd BECAME readable" — reported once. Miss it and you hang
 *        forever, so with EPOLLET you must loop until EAGAIN, every time.
 * Set EDGE=1 in the environment to switch and see the difference in strace.
 */
#include "../common.h"
#include <sys/epoll.h>

#define MAX_EVENTS 512

struct conn {
    int      fd;
    unsigned gen;          /* bumped on every reuse — the "instance" bit */
    int      writing;
    int      len, wpos, olen;
    char     buf[4096];
    char     out[512];
};

static struct conn *slots;
static int slot_max;
static long live = 0;

static struct conn *conn_get(int fd)
{
    if (fd >= slot_max) return NULL;
    struct conn *c = &slots[fd];
    unsigned g = c->gen;
    memset(c, 0, sizeof *c);
    c->gen = g + 1;                       /* the generation survives the wipe */
    c->fd  = fd;
    live++;
    return c;
}

static void conn_close(int epfd, struct conn *c)
{
    if (c->fd < 0) return;
    /* EPOLL_CTL_DEL before close() is optional (closing removes it) but is
     * the habit that saves you when the fd is dup()ed somewhere. */
    epoll_ctl(epfd, EPOLL_CTL_DEL, c->fd, NULL);
    close(c->fd);
    c->fd = -1;
    live--;
}

static void mod(int epfd, struct conn *c, uint32_t events, int add)
{
    struct epoll_event ev;
    memset(&ev, 0, sizeof ev);
    ev.events   = events;
    ev.data.ptr = c;                      /* <- the pointer, not the fd */
    if (epoll_ctl(epfd, add ? EPOLL_CTL_ADD : EPOLL_CTL_MOD, c->fd, &ev) < 0)
        logf_pid("epoll_ctl: %s", strerror(errno));
}

int main(int argc, char **argv)
{
    int port = (argc > 1) ? atoi(argv[1]) : 8004;
    uint32_t et = getenv("EDGE") ? EPOLLET : 0;

    /* One slot per possible descriptor. nginx does the same: it allocates
     * worker_connections structs up front and never mallocs on the request
     * path. Pre-allocation is not an optimisation, it is a latency guarantee.
     *   src/event/ngx_event.c  ngx_event_process_init()  (~L636)  */
    slot_max = 65536;
    slots = calloc((size_t) slot_max, sizeof *slots);
    if (!slots) die("calloc");
    for (int i = 0; i < slot_max; i++) slots[i].fd = -1;

    int lfd = listen_on(port, 511);
    set_nonblocking(lfd);
    signal(SIGPIPE, SIG_IGN);

    int epfd = epoll_create1(0);
    if (epfd < 0) die("epoll_create1");

    struct conn *lc = conn_get(lfd);
    mod(epfd, lc, EPOLLIN, 1);
    live--;                              /* the listener is not a client */

    logf_pid("epolld listening on :%d — one thread, %s-triggered",
             port, et ? "edge" : "level");

    struct epoll_event evs[MAX_EVENTS];
    long peak = 0;

    for (;;) {
        int n = epoll_wait(epfd, evs, MAX_EVENTS, -1);
        if (n < 0) { if (errno == EINTR) continue; die("epoll_wait"); }

        for (int i = 0; i < n; i++) {
            struct conn *c = evs[i].data.ptr;
            uint32_t re = evs[i].events;

            /* The stale check. Cheap, and the alternative is a use-after-free
             * that only shows up under load, in production, at 3am. */
            if (c->fd < 0) continue;

            if (c->fd == lfd) {
                /* Accept in a loop until EAGAIN. Mandatory under EPOLLET,
                 * merely good manners otherwise — one syscall, many clients.
                 *   nginx: src/event/ngx_event_accept.c  ngx_event_accept() (~L21) */
                for (;;) {
                    int cfd = accept4(lfd, NULL, NULL, SOCK_NONBLOCK);
                    if (cfd < 0) {
                        if (errno == EAGAIN || errno == EWOULDBLOCK) break;
                        if (errno == EMFILE || errno == ENFILE) {
                            /* Out of descriptors. nginx keeps a spare fd open
                             * precisely so it can close it, accept, and send a
                             * 503 instead of spinning here. */
                            logf_pid("out of file descriptors (ulimit -n). "
                                     "This is the C10K wall #2.");
                            break;
                        }
                        break;
                    }
                    struct conn *nc = conn_get(cfd);
                    if (!nc) { close(cfd); continue; }
                    mod(epfd, nc, EPOLLIN | et, 1);
                    if (live > peak) {
                        peak = live;
                        if (peak % 500 == 0)
                            logf_pid("peak connections: %ld", peak);
                    }
                }
                continue;
            }

            if (re & (EPOLLHUP | EPOLLERR)) { conn_close(epfd, c); continue; }

            if (re & EPOLLIN) {
                for (;;) {
                    ssize_t r = read(c->fd, c->buf + c->len,
                                     sizeof c->buf - (size_t) c->len - 1);
                    if (r < 0) {
                        if (errno == EAGAIN) break;
                        conn_close(epfd, c);
                        goto next;
                    }
                    if (r == 0) { conn_close(epfd, c); goto next; }
                    c->len += (int) r;
                    c->buf[c->len] = '\0';
                    if (!et) break;      /* level-triggered: one read is fine */
                }

                if (strstr(c->buf, "\r\n\r\n") || strstr(c->buf, "\n\n")) {
                    char body[128];
                    int bn = snprintf(body, sizeof body,
                                      "epolld: %ld live connections\n", live);
                    c->olen = snprintf(c->out, sizeof c->out,
                                       "HTTP/1.1 200 OK\r\n"
                                       "Content-Type: text/plain\r\n"
                                       "Content-Length: %d\r\n"
                                       "Connection: close\r\n\r\n%s", bn, body);
                    c->writing = 1;
                    c->wpos = 0;
                    mod(epfd, c, EPOLLOUT | et, 0);
                }
            }

            if (re & EPOLLOUT) {
                ssize_t w = write(c->fd, c->out + c->wpos,
                                  (size_t) (c->olen - c->wpos));
                if (w <= 0) { conn_close(epfd, c); goto next; }
                c->wpos += (int) w;
                if (c->wpos == c->olen) conn_close(epfd, c);
            }
        next: ;
        }
    }
}
