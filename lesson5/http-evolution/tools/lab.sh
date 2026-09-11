#!/usr/bin/env bash
# lab.sh - start and stop every server the session needs, with pidfiles.
#   tools/lab.sh up      tools/lab.sh down     tools/lab.sh status
set -u
cd "$(dirname "$0")/.."
PIDDIR=out/pids; mkdir -p "$PIDDIR" out

start() { # name cmd...
  local n=$1; shift
  [ -f "$PIDDIR/$n.pid" ] && kill -0 "$(cat "$PIDDIR/$n.pid")" 2>/dev/null && return 0
  nohup "$@" > "out/$n.log" 2>&1 &
  echo $! > "$PIDDIR/$n.pid"
  printf '  started %-12s pid %s\n' "$n" "$!"
}

case "${1:-up}" in
up)
  start s10     python3 01-http10/server10.py 8010
  start s11     python3 02-http11/server11.py 8011
  start lag60   python3 tools/laggy.py 9011 127.0.0.1 8011 --rtt 60  --quiet
  start lag150  python3 tools/laggy.py 9111 127.0.0.1 8011 --rtt 150 --quiet
  sleep 1.2
  for p in 8010 8011 9011 9111; do
    python3 -c "import socket,sys; socket.create_connection(('127.0.0.1',$p),1).close()" \
      2>/dev/null && printf '  :%s listening\n' $p || printf '  :%s NOT LISTENING\n' $p
  done ;;
down)
  for f in "$PIDDIR"/*.pid; do
    [ -e "$f" ] || continue
    kill "$(cat "$f")" 2>/dev/null && printf '  stopped %s\n' "$(basename "$f" .pid)"
    rm -f "$f"
  done ;;
h2|h3)
  start h2     python3 04-http2/h2_server.py 8020
  start h2tls  python3 04-http2/h2_server.py 8443 --tls certs
  start h3     python3 05-http3/h3_server.py 4433 --certs certs
  sleep 1.2; echo "  8020 h2c | 8443 h2+TLS | 4433/udp h3" ;;
status)
  for f in "$PIDDIR"/*.pid; do
    [ -e "$f" ] || continue
    p=$(cat "$f")
    kill -0 "$p" 2>/dev/null && s=up || s=DOWN
    printf '  %-12s %-5s pid %s\n' "$(basename "$f" .pid)" "$s" "$p"
  done ;;
esac
