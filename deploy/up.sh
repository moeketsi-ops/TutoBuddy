#!/usr/bin/env bash
# Build and start Katlego on the server:  sudo bash deploy/up.sh
set -euo pipefail
cd "$(dirname "$0")"
C="docker compose -f docker-compose.server.yml"
for f in /opt/katlego/secrets.env /opt/katlego/db.env /opt/katlego/aws.env; do
  [ -f "$f" ] || { echo "Missing $f. Run set-secrets.sh / the CloudShell key step first."; exit 1; }
done
$C build
$C up -d db redis
if [ ! -f /opt/katlego/.seeded ]; then
  echo "First run: loading curriculum content (seed)..."
  $C run --rm seed && touch /opt/katlego/.seeded
fi
$C up -d worker bridge
$C ps
echo; echo "Logs:  sudo $C logs -f --tail 50 bridge worker"
free -h | sed -n 1,3p
