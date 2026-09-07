/*
 * 06a — a FastCGI application server in 200 lines. Put nginx in front of it.
 *
 *   ./fcgi_responder 9000
 *   nginx -c $PWD/../07-nginx/fastcgi.conf -p $PWD/../07-nginx
 *   curl 'localhost:8080/hello?a=1'
 *
 * This is what php-fpm is, minus PHP. It never forks, never execs, and never
 * parses an HTTP request — nginx did that, and handed over the results as
 * name-value pairs. That is the entire difference between CGI and FastCGI:
 *
 *   CGI      new process + new address space + new interpreter, per request.
 *            Environment goes in via environ; body via stdin; response via
 *            stdout; the process dies. ~5-20 ms of setup before your code runs.
 *   FastCGI  a long-lived process. Environment goes in as PARAMS records;
 *            body as STDIN records; response as STDOUT records; the process
 *            stays. ~0 ms of setup.
 *
 * Same three streams. The only thing that changed is who pays for the setup,
 * and how often. (Session 3's first closing idea, made runnable.)
 *
 * Run it, then run `ps` while you hammer it. The process count does not move.
 * Do the same against a CGI script and count the processes going by.
 */
#include "../common.h"
#include "fastcgi.h"

static int read_full(int fd, void *buf, size_t n)
{
    size_t got = 0;
    while (got < n) {
        ssize_t r = read(fd, (char *) buf + got, n - got);
        if (r <= 0) return 0;
        got += (size_t) r;
    }
    return 1;
}

static void write_record(int fd, int type, int reqid,
                         const void *data, size_t len)
{
    fcgi_header h;
    /* Padding to an 8-byte boundary. Purely so the receiver's reads stay
     * aligned; the spec says SHOULD, everyone does it, nothing breaks if
     * you send zero. nginx sends aligned records. */
    size_t pad = (8 - (len % 8)) % 8;
    static const unsigned char zeros[8] = {0};

    fcgi_fill_header(&h, type, reqid, (int) len, (int) pad);
    (void) !write(fd, &h, sizeof h);
    if (len) (void) !write(fd, data, len);
    if (pad) (void) !write(fd, zeros, pad);
}

/* One connection = one request, because that is all nginx ever sends. */
static void handle(int cfd)
{
    char params[16384];
    size_t plen = 0;
    char body[16384];
    size_t blen = 0;
    int reqid = 1;
    int saw_end_of_params = 0, saw_end_of_stdin = 0;

    while (!(saw_end_of_params && saw_end_of_stdin)) {
        fcgi_header h;
        if (!read_full(cfd, &h, sizeof h)) return;

        int type = h.type;
        int clen = (h.contentLengthB1 << 8) | h.contentLengthB0;
        reqid    = (h.requestIdB1 << 8) | h.requestIdB0;

        fprintf(stderr, "  <- %-14s id=%d len=%d pad=%d\n",
                fcgi_type_name(type), reqid, clen, h.paddingLength);

        char tmp[65536];
        if (clen && !read_full(cfd, tmp, (size_t) clen)) return;
        if (h.paddingLength) {
            char junk[256];
            if (!read_full(cfd, junk, h.paddingLength)) return;
        }

        switch (type) {
        case FCGI_BEGIN_REQUEST: {
            fcgi_begin_body *b = (fcgi_begin_body *) tmp;
            int role = (b->roleB1 << 8) | b->roleB0;
            fprintf(stderr, "     role=%d keep_conn=%d\n",
                    role, b->flags & FCGI_KEEP_CONN);
            break;
        }
        case FCGI_PARAMS:
            /* THE DELIMITER. An empty PARAMS record ends the stream. */
            if (clen == 0) { saw_end_of_params = 1; break; }
            if (plen + (size_t) clen < sizeof params) {
                memcpy(params + plen, tmp, (size_t) clen);
                plen += (size_t) clen;
            }
            break;
        case FCGI_STDIN:
            if (clen == 0) { saw_end_of_stdin = 1; break; }
            if (blen + (size_t) clen < sizeof body) {
                memcpy(body + blen, tmp, (size_t) clen);
                blen += (size_t) clen;
            }
            break;
        case FCGI_ABORT_REQUEST:
            fprintf(stderr, "     client went away; abandoning\n");
            return;
        default:
            break;
        }
    }

    /* Decode the name-value pairs we were handed. These are exactly the
     * variables CGI would have put in environ — REQUEST_METHOD, QUERY_STRING,
     * SCRIPT_NAME, and so on. Apache's version of this list lives in
     * server/util_script.c, ap_add_cgi_vars(). Same names, 30 years on. */
    char out[32768];
    int n = snprintf(out, sizeof out,
                     "Content-Type: text/plain\r\n"
                     "X-Served-By: fcgi_responder pid %d\r\n"
                     "\r\n"
                     "FastCGI responder, pid %d\n"
                     "----------------------------------------\n",
                     (int) getpid(), (int) getpid());

    unsigned char *p   = (unsigned char *) params;
    unsigned char *end = p + plen;
    while (p < end) {
        size_t nl = fcgi_get_len(&p);
        size_t vl = fcgi_get_len(&p);
        if (p + nl + vl > end) break;
        n += snprintf(out + n, sizeof out - (size_t) n,
                      "%.*s = %.*s\n", (int) nl, p, (int) vl, p + nl);
        p += nl + vl;
    }
    if (blen)
        n += snprintf(out + n, sizeof out - (size_t) n,
                      "----------------------------------------\n"
                      "body (%zu bytes): %.*s\n", blen, (int) blen, body);

    /* Response goes out as STDOUT records, then an EMPTY STDOUT record to
     * close the stream, then END_REQUEST. Note the response *headers* are
     * inside the STDOUT stream, CGI-style — blank line separated. nginx
     * parses them out in ngx_http_fastcgi_process_header() (~L1735). */
    write_record(cfd, FCGI_STDOUT, reqid, out, (size_t) n);
    write_record(cfd, FCGI_STDOUT, reqid, NULL, 0);          /* delimiter */

    fcgi_end_body e;
    memset(&e, 0, sizeof e);
    e.protocolStatus = FCGI_REQUEST_COMPLETE;
    write_record(cfd, FCGI_END_REQUEST, reqid, &e, sizeof e);

    fprintf(stderr, "  -> STDOUT %d bytes, STDOUT 0 (eof), END_REQUEST\n\n", n);
}

int main(int argc, char **argv)
{
    int port = (argc > 1) ? atoi(argv[1]) : 9000;
    int lfd  = listen_on(port, 511);
    signal(SIGPIPE, SIG_IGN);

    logf_pid("fcgi_responder on :%d — this process serves every request", port);
    logf_pid("point nginx at it:  fastcgi_pass 127.0.0.1:%d;", port);

    for (;;) {
        int cfd = accept(lfd, NULL, NULL);
        if (cfd < 0) { if (errno == EINTR) continue; die("accept"); }
        fprintf(stderr, "--- connection ---\n");
        handle(cfd);
        close(cfd);
    }
}
