#!/usr/bin/env python3
"""
headers.py - how much of your bandwidth is the same bytes, over and over.

HTTP/1.1 headers are text, they are not compressed (Content-Encoding compresses
the BODY), and they are re-sent in full on every single request. A modern page
makes 70-plus requests to the same origin, each carrying an identical cookie,
an identical User-Agent and an identical Accept-Language.

    python3 03-limits/headers.py --requests 80

Compare the total with what HPACK (04-http2/hpack_mini.py) does to the same set.
"""
import argparse

# A realistic modern request. Nothing here is invented; this is roughly what
# Chrome sends to a logged-in site.
REQ = {
    ":method": "GET",
    ":path": "/assets/app.9f2b1c.js",
    ":authority": "shop.example.com",
    ":scheme": "https",
    "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36",
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,"
              "image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    "accept-encoding": "gzip, deflate, br, zstd",
    "accept-language": "en-GB,en-US;q=0.9,en;q=0.8,hi;q=0.7",
    "cookie": "session_id=8f14e45fceea167a5a36dedd4bea2543; cart=a3f8c1b2d4e5;"
              " _ga=GA1.2.1234567890.1712345678; _gid=GA1.2.9876543210.1712345678;"
              " ab_bucket=variant_c; csrftoken=Q2h1Y2tOb3JyaXNXYXNIZXJl",
    "referer": "https://shop.example.com/checkout",
    "sec-ch-ua": '"Chromium";v="140", "Not=A?Brand";v="24"',
    "sec-fetch-dest": "script",
    "sec-fetch-mode": "no-cors",
    "sec-fetch-site": "same-origin",
}


def http1_bytes(d, path):
    """Exactly what goes on an HTTP/1.1 wire."""
    lines = [f"{d[':method']} {path} HTTP/1.1", f"Host: {d[':authority']}"]
    lines += [f"{k}: {v}" for k, v in d.items() if not k.startswith(":")]
    return len("\r\n".join(lines).encode()) + 4


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--requests", type=int, default=80)
    a = ap.parse_args()

    one = http1_bytes(REQ, REQ[":path"])
    # Only the path changes between the assets of one page.
    paths = [f"/assets/chunk-{i:03d}.js" for i in range(a.requests)]
    total = sum(http1_bytes(REQ, p) for p in paths)
    news = sum(len(p) for p in paths)      # the only bytes carrying information
    repeated = total - news

    print(f"  one request, headers only        {one:>8} bytes")
    print(f"  x {a.requests} requests for one page       {total:>8} bytes")
    print(f"  new information (the paths)      {news:>8} bytes"
          f"   {100*news/total:>5.1f}%")
    print(f"  byte-for-byte repeats            {repeated:>8} bytes"
          f"   {100*repeated/total:>5.1f}%")
    print()
    print(f"  On a 1 Mbit uplink that is {total*8/1_000_000:.2f} s of upload before")
    print(f"  a single byte of your application data has moved.")
    print(f"  HPACK's job is that {100*repeated/total:.1f}%. See 04-http2/hpack_mini.py.")
