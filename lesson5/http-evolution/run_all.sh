#!/usr/bin/env bash
# run_all.sh - every demo in the session, in the order the slides use them.
#   ./run_all.sh            (about 40 seconds)
#   ./run_all.sh 2>&1 | tee out/transcript.txt
set -u
cd "$(dirname "$0")"
mkdir -p out
sec() { printf '\n\n\033[1;33m════ %s\033[0m\n' "$*"; }

./tools/lab.sh down >/dev/null 2>&1
./tools/lab.sh up
nohup python3 04-http2/h2_server.py 8020            > out/h2.log    2>&1 & echo $! > out/pids/h2.pid
nohup python3 04-http2/h2_server.py 8443 --tls certs > out/h2tls.log 2>&1 & echo $! > out/pids/h2tls.pid
nohup python3 05-http3/h3_server.py 4433 --certs certs > out/h3.log 2>&1 & echo $! > out/pids/h3.pid
nohup python3 tools/stall_tcp.py 9020 127.0.0.1 8020 --after 3000 --stall 300 > out/stall.log 2>&1 & echo $! > out/pids/stall.pid
nohup python3 tools/lossy_udp.py 4533 127.0.0.1 4433 --loss 0.05 --skip 10    > out/lossy.log 2>&1 & echo $! > out/pids/lossy.pid
nohup python3 tools/lossy_udp.py 4733 127.0.0.1 4433 --loss 0 --rtt 150       > /dev/null      2>&1 & echo $! > out/pids/lossy150.pid
nohup python3 tools/laggy.py 9543 127.0.0.1 8443 --rtt 150 --quiet            > /dev/null      2>&1 & echo $! > out/pids/lag543.pid
sleep 2

sec "HOUR 1 - HTTP/1.0 (RFC 1945, May 1996)"
echo "-- a request by hand, and the FIN that follows every response"
python3 tools/talk.py 8010 --req "GET / HTTP/1.0" ""
echo; echo "-- OPTIONS does not exist yet"
python3 tools/talk.py 8010 --req "OPTIONS / HTTP/1.0" "" 2>/dev/null | head -1
echo "-- Host is ignored: one server, one site"
python3 tools/talk.py 8010 --req "GET / HTTP/1.0" "Host: site-b.example" "" 2>/dev/null | grep -o '<h1>.*</h1>'

sec "HOUR 2 - HTTP/1.1 (RFC 2068 Jan 1997 / RFC 2616 Jun 1999)"
./02-http11/demos.sh

sec "HOUR 3 - what HTTP/1.1 cost"
echo "-- Nagle + delayed ACK, the bug every HTTP server has had once"
python3 03-limits/nagle.py --port 8011
echo; echo "-- the same page, five ways, at three round-trip times"
for p in "8011 0" "9011 60" "9111 150"; do set -- $p; python3 03-limits/fetch_page.py --port $1 --rtt $2; echo; done
echo "-- head-of-line blocking: pipelining's fatal flaw"
python3 03-limits/hol.py --port 8011 --slow 2.0
echo; echo "-- header bloat"
python3 03-limits/headers.py --requests 80
echo; echo "-- Content-Length vs Transfer-Encoding: the desync"
python3 03-limits/framing.py --port 8011 2>/dev/null | tail -12

sec "HOUR 4 - HTTP/2 (RFC 9113, June 2022; was RFC 7540, May 2015)"
echo "-- HPACK from scratch, against the RFC 7541 Appendix C vectors"
python3 04-http2/hpack_mini.py
echo; echo "-- a hand-written h2 client: preface, frames, streams"
python3 04-http2/h2_client.py --port 8020 --path /
echo; echo "-- over TLS, negotiated by ALPN"
python3 04-http2/h2_client.py --port 8443 --tls --path /style.css 2>&1 | head -2
echo; echo "-- MULTIPLEXING: the same six requests as the HoL demo"
python3 04-http2/h2_client.py --port 8020 --multiplex --slow 2.0 -q

sec "HOUR 5 - QUIC and HTTP/3 (RFC 9000 May 2021 / RFC 9114 June 2022)"
echo "-- HTTP/3 request"
python3 05-http3/h3_client.py --port 4433 --path /coffee 2>&1 | head -6
echo; echo "-- multiplexing over QUIC"
python3 05-http3/h3_client.py --port 4433 --multiplex --slow 2.0 2>/dev/null
echo; echo "-- HEAD-OF-LINE BLOCKING, the part HTTP/2 could not fix"
echo "   [a] HTTP/2 over TCP, one 300 ms stall in the byte stream."
echo "       Three runs, because WHICH streams get caught behind the hole is a"
echo "       lottery decided by byte offsets you do not control - and that is"
echo "       exactly the complaint:"
for i in 1 2 3; do
  echo "       --- run $i ---"
  python3 04-http2/h2_client.py --port 9020 --multiplex --slow 0 -q 2>/dev/null \
    | grep -E '^ +stream' | sed 's/^/    /'
  sleep 0.5
done
echo "   [b] HTTP/3 over QUIC, 5% of datagrams really dropped:"
python3 05-http3/h3_client.py --port 4533 --multiplex --slow 0 2>/dev/null
echo "       datagrams actually dropped: $(grep -c dropped out/lossy.log)"
echo; echo "-- round trips before the first byte, at 150 ms RTT"
python3 05-http3/handshake_race.py --rtt 150 --tcp-port 9543 --quic-port 4733 2>/dev/null

echo; echo; echo "  done. ./tools/lab.sh down  to stop everything."
