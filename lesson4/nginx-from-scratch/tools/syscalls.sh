#!/usr/bin/env bash
# syscalls.sh MODE — count syscalls for one 05-sendfile transfer.
#
#   tools/syscalls.sh read
#   tools/syscalls.sh sendfile
#
# The number in the "calls" column next to write/sendfile is the lesson.
set -u
MODE="${1:-sendfile}"
PID=$(pgrep -x sendfiled || true)
if [ -z "$PID" ]; then
  echo "start it first:  make run-sendfile" >&2; exit 1
fi
echo "tracing pid $PID for mode=$MODE ..."
strace -f -c -p "$PID" -o /tmp/strace.$MODE &
TRACE=$!
sleep 0.4
curl -s "localhost:8005/?mode=$MODE" -o /dev/null
sleep 0.4
kill -INT $TRACE 2>/dev/null; wait $TRACE 2>/dev/null
echo; cat /tmp/strace.$MODE
