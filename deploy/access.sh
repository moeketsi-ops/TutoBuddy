#!/usr/bin/env bash
# Access codes and investor demo, on the server:
#   sudo bash deploy/access.sh issue --kind pilot --days 30 --count 10 --label "School name"
#   sudo bash deploy/access.sh issue --kind demo --days 7 --max-uses 100 --label investors --code KATLEGO-DEMO-XXXX
#   sudo bash deploy/access.sh codes | grants | waitlist [--full] | grant --phone 078... --days 30
#   sudo bash deploy/access.sh revoke-code CODE | revoke-phone --phone 078... | purge-demo
# Full help: sudo bash deploy/access.sh --help
set -euo pipefail
cd "$(dirname "$0")"
exec docker compose -f docker-compose.server.yml run --rm -T worker python -m app.access_admin "$@"
