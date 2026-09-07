/*
 * 03 — one thread, select().  1983 API, still in every libc, still broken
 *      in exactly the way it was broken in 1983.
 *
 *   ./selectd 8003
 *   curl localhost:8003/
 *   tools/flood.sh 8003 1100        # <- the interesting run
 *
 * The wall
 * --------
 * fd_set is a fixed-size bitmap. On glibc/Linux it is FD_SETSIZE bits, and
 * FD_SETSIZE is 1024, hard-coded at compile time in <sys/select.h>. FD_SET()
 * on a descriptor >= 1024 writes off the end of the struct. It does not
 * return an error. It does not warn. It corrupts the stack.
 *
 * This program refuses to do that (see GUARD below) so that you get a clean
 * message instead of a mystery crash. Delete the guard and run flood.sh with
 * 1100 and you will get the mystery crash — do it once, on purpose, so you
 * recognise it for the rest of your life.
 *
 * Note that `ulimit -n 65536` does NOT help. The limit is not the descriptor
 * limit, it is the width of a bitmap in a header file.
 *
 * The other wall
 * --------------
 * Every call to select() is O(n) twice over:
 *   - you rebuild the fd_set from scratch (the kernel destroys it in place),
 *   - the kernel walks all n descriptors to fill it back in,
 *   - and you walk all n again to find out which ones fired.
 * At 10,000 connections with 10 active, you do 30,000 units of work to find
 * 10 events. epoll (04) is O(active), not O(watched). That is the entire
 * difference. Everything else is detail.
 *
 * Where nginx keeps its select
 * ----------------------------
 *   src/event/modules/ngx_select_module.c   ngx_select_process_events()  (~L222)
 *   nginx still ships it — it is the fallback when nothing better exists.
 *   Read it next to ngx_epoll_module.c and the two are the same shape.
 */
#include "../common.h"
#include <sys/select.h>

#define MAXCONN 1024

struct conn {
    int  fd;
    char buf[4096];
    int  len;
    int  writing;
    int  wpos;
    char out[512];
    int  olen;
};

static struct conn conns[MAXCONN];
static int nconn = 0;

static struct conn *conn_add(int fd)
{
    if (nconn >= MAXCONN) return NULL;
    struct conn *c = &conns[nconn++];
    memset(c, 0, sizeof *c);
    c->fd = fd;
    return c;
}

static void conn_del(struct conn *c)
{
    close(c->fd);
    *c = conns[--nconn];        /* swap-remove; order does not matter here */
}

int main(int argc, char **argv)
{
    int port = (argc > 1) ? atoi(argv[1]) : 8003;
    int lfd  = listen_on(port, 511);
    set_nonblocking(lfd);

    signal(SIGPIPE, SIG_IGN);   /* a client that vanishes mid-write is normal */

    logf_pid("selectd listening on :%d — one thread, FD_SETSIZE = %d",
             port, FD_SETSIZE);

    long loops = 0, peak = 0;

    for (;;) {
        fd_set rfds, wfds;
        FD_ZERO(&rfds);
        FD_ZERO(&wfds);

        int maxfd = lfd;
        FD_SET(lfd, &rfds);

        /* THE O(n) REBUILD. select() clobbers the sets, so this happens
         * on every single iteration of the loop, forever. */
        for (int i = 0; i < nconn; i++) {
            int fd = conns[i].fd;
            if (fd > maxfd) maxfd = fd;
            if (conns[i].writing) FD_SET(fd, &wfds);
            else                  FD_SET(fd, &rfds);
        }

        int ready = select(maxfd + 1, &rfds, &wfds, NULL, NULL);
        if (ready < 0) { if (errno == EINTR) continue; die("select"); }

        loops++;
        if (nconn > peak) {
            peak = nconn;
            if (peak % 100 == 0)
                logf_pid("peak connections: %ld  (loops: %ld)", peak, loops);
        }

        if (FD_ISSET(lfd, &rfds)) {
            for (;;) {
                int cfd = accept(lfd, NULL, NULL);
                if (cfd < 0) break;             /* EAGAIN: drained */

                /* ---- GUARD ---------------------------------------------
                 * Delete these six lines to meet the real bug. */
                if (cfd >= FD_SETSIZE) {
                    logf_pid("fd %d >= FD_SETSIZE (%d). select() CANNOT watch "
                             "this descriptor. Closing. This is the wall.",
                             cfd, FD_SETSIZE);
                    close(cfd);
                    continue;
                }
                /* --------------------------------------------------------- */

                set_nonblocking(cfd);
                if (!conn_add(cfd)) {
                    logf_pid("connection table full at %d", MAXCONN);
                    close(cfd);
                }
            }
        }

        /* Walk backwards: conn_del() swap-removes, so forward iteration
         * would skip an entry. A real bug, found the real way. */
        for (int i = nconn - 1; i >= 0; i--) {
            struct conn *c = &conns[i];

            if (!c->writing && FD_ISSET(c->fd, &rfds)) {
                ssize_t n = read(c->fd, c->buf + c->len,
                                 sizeof c->buf - (size_t) c->len - 1);
                if (n <= 0) { conn_del(c); continue; }
                c->len += (int) n;
                c->buf[c->len] = '\0';

                /* Framing, again: the delimiter is a blank line.
                 * Session 2's closing idea, in five lines of C. */
                if (strstr(c->buf, "\r\n\r\n") || strstr(c->buf, "\n\n")) {
                    char body[128];
                    int bn = snprintf(body, sizeof body,
                                      "selectd: %d live connections\n", nconn);
                    c->olen = snprintf(c->out, sizeof c->out,
                                       "HTTP/1.1 200 OK\r\n"
                                       "Content-Type: text/plain\r\n"
                                       "Content-Length: %d\r\n"
                                       "Connection: close\r\n\r\n%s", bn, body);
                    c->writing = 1;
                    c->wpos = 0;
                }
                continue;
            }

            if (c->writing && FD_ISSET(c->fd, &wfds)) {
                ssize_t n = write(c->fd, c->out + c->wpos,
                                  (size_t) (c->olen - c->wpos));
                if (n <= 0) { conn_del(c); continue; }
                c->wpos += (int) n;
                if (c->wpos == c->olen) conn_del(c);
            }
        }
    }
}
