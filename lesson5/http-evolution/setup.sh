#!/usr/bin/env bash
# setup.sh - dependencies and a self-signed certificate.
set -eu
cd "$(dirname "$0")"
python3 -m pip install --quiet h2 hpack aioquic
mkdir -p certs out
[ -f certs/cert.pem ] || openssl req -x509 -newkey rsa:2048 \
  -keyout certs/key.pem -out certs/cert.pem -days 3650 -nodes \
  -subj "/CN=localhost" \
  -addext "subjectAltName=DNS:localhost,DNS:site-a.local,DNS:site-b.local,IP:127.0.0.1"
echo "ready. ./run_all.sh"
