/* common.h — tiny helpers shared by every server in this repo.
 *
 * Nothing clever lives here. The point of the repo is the concurrency model,
 * not the plumbing, so the plumbing is in one place and stays boring.
 */
#ifndef CN_COMMON_H
#define CN_COMMON_H

#define _GNU_SOURCE
#include <arpa/inet.h>
#include <errno.h>
#include <fcntl.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <signal.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

static inline void die(const char *what) { perror(what); exit(1); }

/* Wall-clock milliseconds. CLOCK_MONOTONIC so NTP can't lie to us. */
static inline double now_ms(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return ts.tv_sec * 1000.0 + ts.tv_nsec / 1e6;
}

/*
 * Make a listening socket. Two options here are worth more than the rest of
 * this file put together:
 *
 *   SO_REUSEADDR — lets you restart the server without waiting out TIME_WAIT
 *                  on the listening address. (Session 2, four-way teardown.)
 *   backlog      — the accept queue. Connections that completed the three-way
 *                  handshake but that you have not accept()ed yet sit here.
 *                  Overflow it and the kernel drops SYNs; the client sees a
 *                  hang, not a refusal. `ss -ltn` shows Recv-Q / Send-Q as
 *                  "queued" / "backlog" for listening sockets.
 *
 * nginx: src/core/ngx_connection.c, ngx_open_listening_sockets()
 *        the backlog comes from `listen ... backlog=N`, default 511.
 */
static inline int listen_on(int port, int backlog)
{
    int fd = socket(AF_INET, SOCK_STREAM, 0);
    if (fd < 0) die("socket");

    int on = 1;
    if (setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &on, sizeof on) < 0)
        die("setsockopt(SO_REUSEADDR)");

    struct sockaddr_in a;
    memset(&a, 0, sizeof a);
    a.sin_family = AF_INET;
    a.sin_addr.s_addr = htonl(INADDR_ANY);
    a.sin_port = htons((uint16_t) port);

    if (bind(fd, (struct sockaddr *) &a, sizeof a) < 0) die("bind");
    if (listen(fd, backlog) < 0) die("listen");
    return fd;
}

static inline void set_nonblocking(int fd)
{
    int fl = fcntl(fd, F_GETFL, 0);
    if (fl < 0 || fcntl(fd, F_SETFL, fl | O_NONBLOCK) < 0) die("fcntl");
}

/* Log with a pid prefix so `./forkd` output makes sense next to `ps`. */
static inline void logf_pid(const char *fmt, ...)
{
    va_list ap;
    fprintf(stderr, "[pid %d] ", (int) getpid());
    va_start(ap, fmt);
    vfprintf(stderr, fmt, ap);
    va_end(ap);
    fputc('\n', stderr);
}

/* The smallest thing that a browser will accept as an HTTP response. */
static const char *HTTP_200 =
    "HTTP/1.1 200 OK\r\n"
    "Content-Type: text/plain\r\n"
    "Content-Length: %zu\r\n"
    "Connection: close\r\n"
    "\r\n";

static inline void http_reply(int fd, const char *body)
{
    char hdr[256];
    size_t n = strlen(body);
    int hn = snprintf(hdr, sizeof hdr, HTTP_200, n);
    (void) !write(fd, hdr, (size_t) hn);
    (void) !write(fd, body, n);
}

#endif /* CN_COMMON_H */
