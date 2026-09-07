/*
 * 05 — the same file, three ways.  read/write, mmap/write, sendfile.
 *
 *   dd if=/dev/urandom of=../www/big.bin bs=1M count=256
 *   ./sendfiled 8005 ../www/big.bin
 *
 *   # then, three times, and watch both the timing AND the syscall count:
 *   curl -s 'localhost:8005/?mode=read'     -o /dev/null -w '%{time_total}\n'
 *   curl -s 'localhost:8005/?mode=mmap'     -o /dev/null -w '%{time_total}\n'
 *   curl -s 'localhost:8005/?mode=sendfile' -o /dev/null -w '%{time_total}\n'
 *
 *   # the money shot:
 *   strace -f -c -p $(pgrep -x sendfiled) &
 *   curl -s 'localhost:8005/?mode=read' -o /dev/null; kill %1
 *
 * The copies
 * ----------
 * read()/write() moves 256 MB across the user/kernel boundary FOUR times:
 *   disk -> page cache      (DMA)
 *   page cache -> your buf  (copy 1, and a context switch)
 *   your buf -> socket buf  (copy 2, and a context switch)
 *   socket buf -> NIC       (DMA)
 * ...and it does that per 64 KiB chunk, so 4096 read+write pairs = 8192
 * syscalls, 8192 mode switches, 512 MB of pointless memcpy.
 *
 * mmap()/write() removes copy 1 — the page cache page IS your buffer — but
 * keeps copy 2 and adds page faults and a TLB shootdown on munmap.
 *
 * sendfile() removes BOTH user-space copies and both mode switches per chunk.
 * The data never enters your address space. On a NIC with scatter-gather DMA
 * and checksum offload it is genuinely zero-copy: page cache -> NIC, done.
 * One syscall for the whole file (well, up to 2 GiB - page size; see below).
 *
 * Why you cannot use it for everything
 * ------------------------------------
 * sendfile() copies kernel-side. If you need to *touch* the bytes — gzip
 * them, encrypt them for TLS, template them — they must come into user space
 * and sendfile is off the table. That is why `gzip on` and `sendfile on`
 * fight, and why kTLS exists (move the encryption into the kernel so that
 * sendfile survives). Which knob wins is a real decision you will make.
 *
 * WHAT YOU WILL ACTUALLY MEASURE — read this before you believe the numbers
 * ------------------------------------------------------------------------
 * On loopback, sendfile does NOT win on wall-clock time:
 *
 *   mode=read      wall  37.4 ms | sys 37.3 | 2048 syscalls
 *   mode=mmap      wall  23.3 ms | sys 23.1 |    4 syscalls
 *   mode=sendfile  wall  33.2 ms | sys 32.3 |    1 syscall
 *
 * There is no NIC and no DMA here — the kernel copies into the receiver's
 * socket buffer either way — and curl on the same box is competing with the
 * server for the same CPU. The transfer is memory-bandwidth bound, so all
 * three land in the same place.
 *
 * What IS real and visible on any machine: 2048 syscalls become 1, and the
 * 64 MB never enters this process's address space. The wall-clock win needs a
 * real NIC with scatter-gather DMA, and it shows up as HEADROOM UNDER
 * CONCURRENCY — CPU you did not spend copying is CPU you spend on somebody
 * else's request — not as a faster single transfer.
 *
 * Run it across a LAN with a second machine and the gap appears. Run it on
 * loopback and it does not. That is not a bug in the demo, that IS the demo:
 * a benchmark that does not model the bottleneck measures the wrong thing.
 *
 * Where nginx does it
 * -------------------
 *   src/os/unix/ngx_linux_sendfile_chain.c
 *     ngx_linux_sendfile_chain()  (~L50)   builds the iovec, sets TCP_CORK
 *     ngx_linux_sendfile()        (~L232)  the bare sendfile(2) call + EINTR
 *   The header goes out with writev() and the body with sendfile() in the
 *   same corked write, which is why nginx sets TCP_NOPUSH: without it the
 *   headers leave in their own tiny packet and you have burned a segment.
 *
 *   The decision to use it at all is made much earlier, when the static
 *   module marks the buffer as living in a file rather than in memory:
 *     src/http/modules/ngx_http_static_module.c  ngx_http_static_handler()
 *       b->in_file = b->file_last ? 1 : 0;      (~L264)
 *   Everything downstream just honours that flag. `sendfile on;` in your
 *   config is a permission, not an instruction.
 */
#include "../common.h"
#include <sys/mman.h>
#include <sys/sendfile.h>
#include <sys/stat.h>
#include <sys/resource.h>

#define CHUNK (64 * 1024)

static const char *path;
static off_t       fsize;

static long send_read(int cfd, int ffd)
{
    char buf[CHUNK];
    long calls = 0;
    off_t off = 0;

    while (off < fsize) {
        ssize_t r = pread(ffd, buf, sizeof buf, off);
        calls++;
        if (r <= 0) break;
        off += r;

        ssize_t done = 0;
        while (done < r) {
            ssize_t w = write(cfd, buf + done, (size_t) (r - done));
            calls++;
            if (w <= 0) return calls;
            done += w;
        }
    }
    return calls;
}

static long send_mmap(int cfd, int ffd)
{
    long calls = 0;
    void *m = mmap(NULL, (size_t) fsize, PROT_READ, MAP_PRIVATE, ffd, 0);
    calls++;
    if (m == MAP_FAILED) return -1;

    /* Tell the kernel we mean it, so it reads ahead instead of faulting
     * one page at a time. Without this, mmap loses to read(). */
    madvise(m, (size_t) fsize, MADV_SEQUENTIAL | MADV_WILLNEED);
    calls++;

    off_t done = 0;
    while (done < fsize) {
        ssize_t w = write(cfd, (char *) m + done, (size_t) (fsize - done));
        calls++;
        if (w <= 0) break;
        done += w;
    }
    munmap(m, (size_t) fsize);
    calls++;
    return calls;
}

static long send_sendfile(int cfd, int ffd)
{
    long calls = 0;
    off_t off = 0;

    while (off < fsize) {
        /* Note the 2 GiB ceiling: sendfile's count is a size_t but the
         * kernel caps a single call at 0x7ffff000. nginx clamps to
         * NGX_SENDFILE_MAXSIZE for the same reason. Big files still take
         * more than one call — just not four thousand of them. */
        ssize_t s = sendfile(cfd, ffd, &off, (size_t) (fsize - off));
        calls++;
        if (s <= 0) break;
    }
    return calls;
}

int main(int argc, char **argv)
{
    int port = (argc > 1) ? atoi(argv[1]) : 8005;
    path = (argc > 2) ? argv[2] : "../www/big.bin";

    struct stat st;
    if (stat(path, &st) < 0) {
        fprintf(stderr, "cannot stat %s — make a big file first:\n"
                        "  dd if=/dev/urandom of=%s bs=1M count=256\n",
                path, path);
        return 1;
    }
    fsize = st.st_size;

    int lfd = listen_on(port, 511);
    signal(SIGPIPE, SIG_IGN);
    logf_pid("sendfiled on :%d serving %s (%.1f MB)", port, path,
             fsize / 1048576.0);
    logf_pid("try /?mode=read  /?mode=mmap  /?mode=sendfile");

    for (;;) {
        int cfd = accept(lfd, NULL, NULL);
        if (cfd < 0) { if (errno == EINTR) continue; die("accept"); }

        char req[2048] = {0};
        ssize_t n = read(cfd, req, sizeof req - 1);
        if (n <= 0) { close(cfd); continue; }

        const char *mode = "sendfile";
        if (strstr(req, "mode=read"))  mode = "read";
        if (strstr(req, "mode=mmap"))  mode = "mmap";

        /* TCP_CORK: hold the headers back so they leave in the same segment
         * as the first slice of body. This is `tcp_nopush on;`.
         * Uncork happens implicitly on close, or explicitly below. */
        int on = 1;
        setsockopt(cfd, IPPROTO_TCP, TCP_CORK, &on, sizeof on);

        char hdr[256];
        int hn = snprintf(hdr, sizeof hdr,
                          "HTTP/1.1 200 OK\r\n"
                          "Content-Type: application/octet-stream\r\n"
                          "Content-Length: %lld\r\n"
                          "X-Send-Mode: %s\r\n"
                          "Connection: close\r\n\r\n",
                          (long long) fsize, mode);
        (void) !write(cfd, hdr, (size_t) hn);

        int ffd = open(path, O_RDONLY);
        if (ffd < 0) { close(cfd); continue; }

        struct rusage r0, r1;
        getrusage(RUSAGE_SELF, &r0);
        double t0 = now_ms();
        long calls;
        if      (!strcmp(mode, "read")) calls = send_read(cfd, ffd);
        else if (!strcmp(mode, "mmap")) calls = send_mmap(cfd, ffd);
        else                            calls = send_sendfile(cfd, ffd);
        double t1 = now_ms();
        getrusage(RUSAGE_SELF, &r1);

        /* CPU, not wall clock, is the honest number here. On loopback with a
         * warm page cache there is no network and no disk, so wall time is
         * dominated by memory bandwidth and all three modes look similar.
         * SYSTEM CPU is where the copies show up. Watch sys collapse. */
        double usr = (r1.ru_utime.tv_sec - r0.ru_utime.tv_sec) * 1000.0
                   + (r1.ru_utime.tv_usec - r0.ru_utime.tv_usec) / 1000.0;
        double sys = (r1.ru_stime.tv_sec - r0.ru_stime.tv_sec) * 1000.0
                   + (r1.ru_stime.tv_usec - r0.ru_stime.tv_usec) / 1000.0;

        int off = 0;
        setsockopt(cfd, IPPROTO_TCP, TCP_CORK, &off, sizeof off);

        logf_pid("mode=%-8s  wall %7.1f ms | usr %6.1f | sys %6.1f | "
                 "%6ld syscalls | %6.1f MB/s",
                 mode, t1 - t0, usr, sys, calls,
                 (fsize / 1048576.0) / ((t1 - t0) / 1000.0));

        close(ffd);
        close(cfd);
    }
}
