/*
 * 02 — one pthread per client.  Apache 2.0's worker MPM, roughly. 1999-2002.
 *
 *   ./threadd 8002
 *   curl localhost:8002/
 *   # second screen:
 *   watch -n0.2 'ps -o pid,nlwp,rss,vsz,comm -p $(pgrep -x threadd)'
 *
 * What to watch for
 * -----------------
 *  1. NLWP (number of light-weight processes = threads) climbs with load;
 *     the pid count does not. That is the whole win over 01-fork.
 *  2. VSZ climbs ~8 MB per thread. The program prints the default stack size
 *     at startup — on glibc/Linux it is `ulimit -s`, usually 8192 KiB.
 *     10,000 threads x 8 MB = 80 GB of address space. It is only address
 *     space, not resident memory, but it is the reason nobody ships this.
 *  3. Run with STACK=65536 ./threadd to shrink the stack to 64 KiB and watch
 *     VSZ collapse. That is the knob Apache's ThreadStackSize turns.
 *  4. Nothing here is shared, so nothing here needs a lock. Add one counter
 *     of total requests without a mutex, hammer it, and watch it come out
 *     wrong. That is the 1999 bug that ate everyone's year.
 *
 * Compare
 * -------
 *  A Go goroutine starts at 2 KiB and grows: src/runtime/stack.go, _StackMin.
 *  Same idea, 4000x cheaper, which is why the model came back.
 */
#include "../common.h"
#include <pthread.h>

static volatile long live_threads = 0;   /* deliberately unsynchronised — see #4 */

static void *serve(void *arg)
{
    int cfd = (int) (long) arg;

    __sync_fetch_and_add(&live_threads, 1);

    char req[2048];
    ssize_t n = read(cfd, req, sizeof req - 1);
    if (n > 0) req[n] = '\0';

    char body[256];
    snprintf(body, sizeof body,
             "served by thread %lu\nlive threads: %ld\n",
             (unsigned long) pthread_self(), live_threads);

    sleep(2);                            /* again: so you can watch it in ps */
    http_reply(cfd, body);
    close(cfd);

    __sync_fetch_and_sub(&live_threads, 1);
    return NULL;
}

int main(int argc, char **argv)
{
    int port = (argc > 1) ? atoi(argv[1]) : 8002;
    int lfd  = listen_on(port, 511);

    pthread_attr_t attr;
    pthread_attr_init(&attr);
    /* Detached: nobody is going to pthread_join() these, and an unjoined
     * joinable thread leaks its descriptor block. The threading equivalent
     * of a zombie. */
    pthread_attr_setdetachstate(&attr, PTHREAD_CREATE_DETACHED);

    size_t stack = 0;
    pthread_attr_getstacksize(&attr, &stack);
    logf_pid("default thread stack: %zu bytes (%zu KiB)", stack, stack / 1024);

    const char *env = getenv("STACK");
    if (env) {
        size_t want = (size_t) strtoul(env, NULL, 10);
        if (pthread_attr_setstacksize(&attr, want) == 0) {
            pthread_attr_getstacksize(&attr, &stack);
            logf_pid("stack set to %zu bytes — x10,000 threads = %.1f GB of VA",
                     stack, stack * 10000.0 / 1e9);
        }
    } else {
        logf_pid("x10,000 threads = %.1f GB of address space. Try STACK=65536.",
                 stack * 10000.0 / 1e9);
    }

    logf_pid("threadd listening on :%d — one thread per connection", port);

    for (;;) {
        int cfd = accept(lfd, NULL, NULL);
        if (cfd < 0) { if (errno == EINTR) continue; die("accept"); }

        pthread_t t;
        int rc = pthread_create(&t, &attr, serve, (void *) (long) cfd);
        if (rc != 0) {
            /* EAGAIN here = out of memory for another stack, or RLIMIT_NPROC.
             * Linux counts threads against the process limit too. */
            logf_pid("pthread_create failed: %s", strerror(rc));
            close(cfd);
        }
    }
}
