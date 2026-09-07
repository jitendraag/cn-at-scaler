/*
 * 01 — fork() per client.  The 1994 design. NCSA HTTPd and Apache 1.3 did this.
 *
 *   ./forkd 8001
 *   curl localhost:8001/          # then, on a second screen:
 *   watch -n0.2 'ps -o pid,ppid,rss,vsz,comm -C forkd'
 *
 * What to watch for
 * -----------------
 *  1. One OS process per in-flight request. Not per second — per *in-flight*.
 *     Hold a connection open (`telnet localhost 8001` and type nothing) and
 *     the process stays.
 *  2. RSS per child is small because fork() is copy-on-write; VSZ is not.
 *  3. Kill the parent and the children keep serving. Nobody is in charge.
 *  4. Comment out the SIGCHLD handler, run `tools/flood.sh 8001 200`, then
 *     `ps aux | grep defunct`. Zombies are not a metaphor; they are a real
 *     table with a fixed size.
 *
 * Where nginx does the same thing, once
 * -------------------------------------
 *  nginx forks too — but at startup, not per request:
 *    src/os/unix/ngx_process_cycle.c  ngx_start_worker_processes()   (~L358)
 *    src/os/unix/ngx_process.c        ngx_spawn_process()            (~L87)
 *  That is the whole "amortise the setup" idea from Session 3: the same
 *  syscall, moved off the request path.
 */
#include "../common.h"

static void reap(int sig)
{
    (void) sig;
    /* WNOHANG in a loop: signals coalesce, so N children can die and we may
     * get one SIGCHLD. Never assume one signal means one child. */
    while (waitpid(-1, NULL, WNOHANG) > 0) { }
}

int main(int argc, char **argv)
{
    int port = (argc > 1) ? atoi(argv[1]) : 8001;
    int lfd  = listen_on(port, 511);

    struct sigaction sa;
    memset(&sa, 0, sizeof sa);
    sa.sa_handler = reap;
    sa.sa_flags   = SA_RESTART | SA_NOCLDSTOP;
    sigaction(SIGCHLD, &sa, NULL);

    logf_pid("forkd listening on :%d — one process per connection", port);

    for (;;) {
        struct sockaddr_in cli;
        socklen_t clen = sizeof cli;

        int cfd = accept(lfd, (struct sockaddr *) &cli, &clen);
        if (cfd < 0) {
            if (errno == EINTR) continue;      /* SIGCHLD landed mid-accept */
            die("accept");
        }

        pid_t pid = fork();
        if (pid < 0) {
            /* This is the wall. EAGAIN here means RLIMIT_NPROC or kernel
             * pid exhaustion — the "fork bomb by popularity" failure. */
            logf_pid("fork failed: %s — dropping the connection", strerror(errno));
            close(cfd);
            continue;
        }

        if (pid == 0) {
            /* Child. It inherited lfd; if it does not close it, the listening
             * socket never really closes and restarts get weird. */
            close(lfd);

            char req[2048];
            ssize_t n = read(cfd, req, sizeof req - 1);
            if (n > 0) req[n] = '\0';

            char body[256];
            snprintf(body, sizeof body,
                     "served by pid %d\nppid %d\n", (int) getpid(), (int) getppid());

            /* Sleep so you can actually SEE the process in ps.
             * Real servers do not do this; slow upstreams do it for them. */
            sleep(2);

            http_reply(cfd, body);
            close(cfd);
            _exit(0);
        }

        /* Parent: the child owns the connection now. */
        close(cfd);
    }
}
