/*
 * 06b — be nginx for one request. Speak FastCGI by hand and hexdump it.
 *
 *   ./fcgi_responder 9000 &
 *   ./fcgi_client 127.0.0.1 9000 /hello 'a=1&b=2'
 *
 * ...or point it at a real php-fpm and watch the same bytes work:
 *   ./fcgi_client 127.0.0.1 9000 /index.php 'x=1'
 *
 * This is the Session 2 exercise — telnet to a server and type the protocol —
 * except the protocol is binary, so we type it in C. Everything printed is
 * literally what goes on the wire. Run tcpdump on loopback alongside it:
 *
 *   sudo tcpdump -i lo -X 'port 9000'
 *
 * ...and find FCGI_BEGIN_REQUEST by hand. The first record on every FastCGI
 * connection starts with the bytes 01 01 00 01 00 08 00 00. Learn to spot it
 * and you can read a FastCGI capture without a dissector.
 */
#include "../common.h"
#include "fastcgi.h"
#include <netdb.h>

static void hexdump(const char *label, const unsigned char *p, size_t n)
{
    printf("%s (%zu bytes)\n", label, n);
    for (size_t i = 0; i < n; i += 16) {
        printf("  %04zx  ", i);
        for (size_t j = 0; j < 16; j++) {
            if (i + j < n) printf("%02x ", p[i + j]);
            else           printf("   ");
            if (j == 7) putchar(' ');
        }
        printf(" |");
        for (size_t j = 0; j < 16 && i + j < n; j++) {
            unsigned char c = p[i + j];
            putchar((c >= 32 && c < 127) ? c : '.');
        }
        printf("|\n");
    }
    putchar('\n');
}

static void send_record(int fd, int type, int reqid,
                        const void *data, size_t len, const char *why)
{
    unsigned char frame[65536 + 16];
    fcgi_header *h = (fcgi_header *) frame;
    size_t pad = (8 - (len % 8)) % 8;

    fcgi_fill_header(h, type, reqid, (int) len, (int) pad);
    if (len) memcpy(frame + sizeof *h, data, len);
    if (pad) memset(frame + sizeof *h + len, 0, pad);

    size_t total = sizeof *h + len + pad;

    char label[128];
    snprintf(label, sizeof label, ">> %s  %s", fcgi_type_name(type), why);
    hexdump(label, frame, total);

    if (write(fd, frame, total) != (ssize_t) total) die("write");
}

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

int main(int argc, char **argv)
{
    const char *host  = (argc > 1) ? argv[1] : "127.0.0.1";
    int         port  = (argc > 2) ? atoi(argv[2]) : 9000;
    const char *uri   = (argc > 3) ? argv[3] : "/hello";
    const char *query = (argc > 4) ? argv[4] : "";

    int fd = socket(AF_INET, SOCK_STREAM, 0);
    struct sockaddr_in a;
    memset(&a, 0, sizeof a);
    a.sin_family = AF_INET;
    a.sin_port   = htons((uint16_t) port);
    if (inet_pton(AF_INET, host, &a.sin_addr) != 1) die("inet_pton");
    if (connect(fd, (struct sockaddr *) &a, sizeof a) < 0) die("connect");

    printf("connected to %s:%d — requestId will be 1, as nginx always does\n\n",
           host, port);

    /* 1. BEGIN_REQUEST: role RESPONDER, and DO NOT keep the connection.
     *    nginx sets keep_conn only when `fastcgi_keep_conn on;`. */
    fcgi_begin_body b;
    memset(&b, 0, sizeof b);
    b.roleB0 = FCGI_RESPONDER;
    b.flags  = 0;
    send_record(fd, FCGI_BEGIN_REQUEST, 1, &b, sizeof b,
                "role=RESPONDER, keep_conn=0");

    /* 2. PARAMS: the CGI environment, as length-prefixed name/value pairs.
     *    This exact list is what Apache's ap_add_cgi_vars() would have put
     *    into environ before exec'ing a CGI script. Same variables, no fork. */
    unsigned char params[8192];
    unsigned char *p = params;
    p += fcgi_put_pair(p, "GATEWAY_INTERFACE", "CGI/1.1");
    p += fcgi_put_pair(p, "REQUEST_METHOD",    "GET");
    p += fcgi_put_pair(p, "SCRIPT_FILENAME",   uri);
    p += fcgi_put_pair(p, "SCRIPT_NAME",       uri);
    p += fcgi_put_pair(p, "REQUEST_URI",       uri);
    p += fcgi_put_pair(p, "QUERY_STRING",      query);
    p += fcgi_put_pair(p, "SERVER_PROTOCOL",   "HTTP/1.1");
    p += fcgi_put_pair(p, "SERVER_SOFTWARE",   "fcgi_client/1.0");
    p += fcgi_put_pair(p, "REMOTE_ADDR",       "127.0.0.1");
    p += fcgi_put_pair(p, "HTTP_USER_AGENT",   "cn-scaler-session-4");
    /* An over-127-byte value, so you can see the 4-byte length encoding
     * with the high bit set. Look for 80 00 00 xx in the dump. */
    char big[200];
    memset(big, 'A', sizeof big - 1);
    big[sizeof big - 1] = '\0';
    p += fcgi_put_pair(p, "HTTP_X_LONG_HEADER", big);
    send_record(fd, FCGI_PARAMS, 1, params, (size_t) (p - params),
                "the CGI environment");

    /* 3. THE EMPTY RECORD. This is the end-of-stream delimiter and there is
     *    no other one. Forget it and the responder waits forever. */
    send_record(fd, FCGI_PARAMS, 1, NULL, 0, "<- EMPTY = end of PARAMS");

    /* 4. STDIN: the request body. GET has none, so we send the delimiter
     *    immediately. A POST would send one or more non-empty STDIN records
     *    first. nginx chunks the body into 64 KiB-ish records. */
    send_record(fd, FCGI_STDIN, 1, NULL, 0, "<- EMPTY = end of STDIN (no body)");

    /* 5. Read records back until END_REQUEST. */
    printf("---- response ----\n\n");
    for (;;) {
        fcgi_header h;
        if (!read_full(fd, &h, sizeof h)) { printf("connection closed\n"); break; }

        int clen = (h.contentLengthB1 << 8) | h.contentLengthB0;
        int type = h.type;

        printf("<< %-14s  id=%d  contentLength=%d  padding=%d\n",
               fcgi_type_name(type), (h.requestIdB1 << 8) | h.requestIdB0,
               clen, h.paddingLength);

        unsigned char data[65536];
        if (clen && !read_full(fd, data, (size_t) clen)) break;
        if (h.paddingLength) {
            unsigned char junk[256];
            if (!read_full(fd, junk, h.paddingLength)) break;
        }

        if (type == FCGI_STDOUT && clen == 0)
            printf("   ^ empty STDOUT = the responder is done writing\n\n");
        else if (type == FCGI_STDOUT || type == FCGI_STDERR)
            printf("---\n%.*s\n---\n\n", clen, data);

        if (type == FCGI_END_REQUEST) {
            fcgi_end_body *e = (fcgi_end_body *) data;
            unsigned status = ((unsigned) e->appStatusB3 << 24)
                            | ((unsigned) e->appStatusB2 << 16)
                            | ((unsigned) e->appStatusB1 << 8)
                            |  (unsigned) e->appStatusB0;
            printf("   appStatus=%u protocolStatus=%d — request over\n",
                   status, e->protocolStatus);
            break;
        }
    }

    close(fd);
    return 0;
}
