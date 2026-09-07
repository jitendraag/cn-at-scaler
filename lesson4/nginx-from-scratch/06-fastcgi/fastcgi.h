/*
 * fastcgi.h — the entire FastCGI wire format, in one header you can read.
 *
 * The spec (fastcgi.com, 1996, ~20 pages) is one of the shortest protocol
 * specs worth reading. Everything below is from section 3.
 *
 * A FastCGI record is a length-prefixed frame:
 *
 *    0        1        2        3        4        5        6        7
 * +--------+--------+--------+--------+--------+--------+--------+--------+
 * |version | type   |  requestId (BE) |  contentLength  |padLen  | resv   |
 * +--------+--------+--------+--------+--------+--------+--------+--------+
 * |  contentData[contentLength]  ...                                      |
 * |  paddingData[paddingLength]  ...                                      |
 * +-----------------------------------------------------------------------+
 *
 * Session 2's closing idea, again: framing is length or delimiter, no third
 * option. FastCGI uses BOTH, at two different levels —
 *   - a LENGTH inside each record header (contentLength), and
 *   - a DELIMITER between logical streams: a record of type X with
 *     contentLength == 0 means "stream X is finished".
 * That empty record is the whole trick. An empty PARAMS record means "no more
 * environment variables"; an empty STDIN record means "no more request body".
 * There is no other end-of-stream signal.
 *
 * requestId lets one connection carry many concurrent requests. nginx does
 * not use this — it hardcodes requestId 1 and opens a connection per request:
 *   src/http/modules/ngx_http_fastcgi_module.c  ngx_http_fastcgi_process_record()
 *   (~L2742) — see the comment "we support the single request per connection"
 *   and the explicit check that the low byte is 1.
 */
#ifndef CN_FASTCGI_H
#define CN_FASTCGI_H

#include <stdint.h>
#include <string.h>

#define FCGI_VERSION_1 1

/* Record types (spec section 3.3 / 3.4) */
#define FCGI_BEGIN_REQUEST      1
#define FCGI_ABORT_REQUEST      2
#define FCGI_END_REQUEST        3
#define FCGI_PARAMS             4
#define FCGI_STDIN              5
#define FCGI_STDOUT             6
#define FCGI_STDERR             7
#define FCGI_DATA               8
#define FCGI_GET_VALUES         9
#define FCGI_GET_VALUES_RESULT 10
#define FCGI_UNKNOWN_TYPE      11

/* Roles */
#define FCGI_RESPONDER  1
#define FCGI_AUTHORIZER 2
#define FCGI_FILTER     3

/* BEGIN_REQUEST flags */
#define FCGI_KEEP_CONN  1

/* END_REQUEST protocolStatus */
#define FCGI_REQUEST_COMPLETE 0
#define FCGI_CANT_MPX_CONN    1
#define FCGI_OVERLOADED       2
#define FCGI_UNKNOWN_ROLE     3

typedef struct {
    unsigned char version;
    unsigned char type;
    unsigned char requestIdB1, requestIdB0;
    unsigned char contentLengthB1, contentLengthB0;
    unsigned char paddingLength;
    unsigned char reserved;
} fcgi_header;

typedef struct {
    unsigned char roleB1, roleB0;
    unsigned char flags;
    unsigned char reserved[5];
} fcgi_begin_body;

typedef struct {
    unsigned char appStatusB3, appStatusB2, appStatusB1, appStatusB0;
    unsigned char protocolStatus;
    unsigned char reserved[3];
} fcgi_end_body;

static inline const char *fcgi_type_name(int t)
{
    switch (t) {
    case FCGI_BEGIN_REQUEST:      return "BEGIN_REQUEST";
    case FCGI_ABORT_REQUEST:      return "ABORT_REQUEST";
    case FCGI_END_REQUEST:        return "END_REQUEST";
    case FCGI_PARAMS:             return "PARAMS";
    case FCGI_STDIN:              return "STDIN";
    case FCGI_STDOUT:             return "STDOUT";
    case FCGI_STDERR:             return "STDERR";
    case FCGI_DATA:               return "DATA";
    case FCGI_GET_VALUES:         return "GET_VALUES";
    case FCGI_GET_VALUES_RESULT:  return "GET_VALUES_RESULT";
    case FCGI_UNKNOWN_TYPE:       return "UNKNOWN_TYPE";
    default:                      return "???";
    }
}

static inline void fcgi_fill_header(fcgi_header *h, int type, int reqid,
                             int clen, int plen)
{
    h->version         = FCGI_VERSION_1;
    h->type            = (unsigned char) type;
    h->requestIdB1     = (unsigned char) ((reqid >> 8) & 0xff);
    h->requestIdB0     = (unsigned char) (reqid & 0xff);
    h->contentLengthB1 = (unsigned char) ((clen >> 8) & 0xff);
    h->contentLengthB0 = (unsigned char) (clen & 0xff);
    h->paddingLength   = (unsigned char) plen;
    h->reserved        = 0;
}

/*
 * Name-value pair encoding (spec 3.4). This is the one genuinely fiddly bit.
 * A length under 128 is one byte. A length of 128 or more is four bytes,
 * big-endian, with the top bit of the FIRST byte set as the marker.
 *
 * So the length field is self-describing: read one byte; if the high bit is
 * clear that byte IS the length; if it is set, this is a 4-byte length and
 * you mask the high bit off. A varint, twenty years before protobuf.
 *
 * nginx builds these in ngx_http_fastcgi_create_request()  (~L858) — look for
 * the `len > 127` branches. It computes the whole size first, allocates once,
 * then fills. No realloc on the request path.
 */
static inline int fcgi_put_len(unsigned char *p, size_t len)
{
    if (len < 128) { p[0] = (unsigned char) len; return 1; }
    p[0] = (unsigned char) (((len >> 24) & 0xff) | 0x80);
    p[1] = (unsigned char) ((len >> 16) & 0xff);
    p[2] = (unsigned char) ((len >> 8) & 0xff);
    p[3] = (unsigned char) (len & 0xff);
    return 4;
}

static inline size_t fcgi_put_pair(unsigned char *p, const char *name, const char *val)
{
    size_t nl = strlen(name), vl = strlen(val);
    unsigned char *s = p;
    p += fcgi_put_len(p, nl);
    p += fcgi_put_len(p, vl);
    memcpy(p, name, nl); p += nl;
    memcpy(p, val,  vl); p += vl;
    return (size_t) (p - s);
}

/* Reads a length back off the wire; advances *p. */
static inline size_t fcgi_get_len(unsigned char **p)
{
    size_t len;
    if (**p & 0x80) {
        len = (size_t) (((*p)[0] & 0x7f) << 24 | (*p)[1] << 16
                        | (*p)[2] << 8 | (*p)[3]);
        *p += 4;
    } else {
        len = **p;
        *p += 1;
    }
    return len;
}

#endif /* CN_FASTCGI_H */
