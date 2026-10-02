#!/usr/bin/env bash
# Bygger, startar och testar header-capture i Docker, inklusive persistens efter omstart.
set -euo pipefail
cd "$(dirname "$0")"
URL=http://localhost:8000

wait_up() { for _ in $(seq 1 30); do curl -sf "$URL/health" >/dev/null && return 0; sleep 1; done; echo "Svarar inte"; exit 1; }

echo "== Bygger image =="
docker compose build

echo "== Startar container =="
docker compose up -d
wait_up
docker compose ps

echo "== GET / =="
curl -s -o /dev/null -w "HTTP %{http_code}\n" "$URL/"

echo "== Testanrop =="
curl -s -X POST "$URL/capture" \
  -H "Content-Type: application/json" \
  -H "X-Custom-Header: custom-value" \
  -H "X-Bifrost-Test: hello" \
  -d '{"message":"test från lokal docker"}'
echo

check_page() {
  local page; page=$(curl -s "$URL/")
  for s in "X-Custom-Header" "custom-value" "X-Bifrost-Test" "hello" "test från lokal docker"; do
    if grep -q "$s" <<<"$page"; then echo "  OK      $s"; else echo "  SAKNAS  $s"; exit 1; fi
  done
}

echo "== Syns på webbsidan? =="
check_page

echo "== Startar om containern =="
docker compose restart
wait_up

echo "== Finns kvar efter omstart? =="
check_page

echo
echo "Alla tester OK. Öppna $URL/"
