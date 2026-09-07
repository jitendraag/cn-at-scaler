#!/usr/bin/env bash
# flood.sh PORT N — open N connections, hold them, count how many stuck.
#
#   tools/flood.sh 8003 1100     # kills selectd
#   tools/flood.sh 8004 5000     # epolld shrugs
#
# Each connection sends a partial request (no blank line) so the server has to
# HOLD it rather than answer and close. That is the point: idle-but-open is
# the state that costs, and the state select() is bad at.
#
# You will need:  ulimit -n 65536
set -u
PORT="${1:-8003}"
N="${2:-1100}"

echo "opening $N connections to :$PORT (ulimit -n is $(ulimit -n))"

python3 - "$PORT" "$N" <<'PY'
import socket, sys, time
port, n = int(sys.argv[1]), int(sys.argv[2])
socks, failed = [], 0
t0 = time.time()
for i in range(n):
    try:
        s = socket.create_connection(("127.0.0.1", port), timeout=2)
        s.sendall(b"GET / HTTP/1.1\r\nHost: x\r\n")   # deliberately unfinished
        socks.append(s)
    except OSError as e:
        failed += 1
        if failed < 5:
            print(f"  connection {i} failed: {e}")
    if i and i % 250 == 0:
        print(f"  {i} open, {failed} failed, {time.time()-t0:.1f}s")
print(f"\nheld open: {len(socks)}   failed: {failed}   in {time.time()-t0:.1f}s")
print("holding for 10s — check the server's log and `ss -tn state established | wc -l`")
time.sleep(10)
for s in socks:
    try: s.close()
    except OSError: pass
print("closed")
PY
