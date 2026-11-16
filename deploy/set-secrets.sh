#!/usr/bin/env bash
# Run ON the server (Lightsail browser SSH):  sudo bash deploy/set-secrets.sh
# Asks for each secret with hidden typing and writes /opt/katlego/secrets.env
# and db.env (root only, mode 600). Nothing is echoed or logged.
set -euo pipefail
H=/opt/katlego
mkdir -p "$H"
umask 077

# Hidden input. Paste works (Ctrl+V / Ctrl+Shift+V / right-click). Stray spaces,
# quotes and line breaks from copying are stripped.
ask() { local v; read -r -s -p "$1: " v </dev/tty || { echo >&2; echo "Input closed before Enter (nothing written)." >&2; return 1; }; echo >&2; v=${v//[[:space:]\"\']/}; printf '%s' "$v"; }
askv() { local v; read -r -p "$1: " v </dev/tty || true; printf '%s' "$v"; }
trap 'echo; echo "Stopped (nothing written)." >&2' INT

# Each key is tested live, so a bad paste is caught here, not in a learner chat.
while :; do
  TOKEN=$(ask "Paste the Katlego Bot WhatsApp token (the never-expiring one)") || exit 1
  OUT=$(curl -s -m 15 -H @- "https://graph.facebook.com/v25.0/1352337571306417?fields=display_phone_number,verified_name" <<<"Authorization: Bearer $TOKEN" || true)
  if grep -q display_phone_number <<<"$OUT"; then
    echo "  OK: token works for $(sed -n 's/.*"display_phone_number":"\([^"]*\)".*/\1/p' <<<"$OUT") (${#TOKEN} chars)"; break
  fi
  echo "  That token did not work (${#TOKEN} chars; Meta says: $(sed -n 's/.*"message":"\([^"]*\)".*/\1/p' <<<"$OUT" | cut -c1-80)). Try pasting again." >&2
done
while :; do
  OR_KEY=$(ask "Paste the OpenRouter API key") || exit 1
  CODE=$(curl -s -m 15 -o /dev/null -w '%{http_code}' -H @- https://openrouter.ai/api/v1/key <<<"Authorization: Bearer $OR_KEY" || true)
  [ "$CODE" = 200 ] && { echo "  OK: OpenRouter key works (${#OR_KEY} chars)"; break; }
  echo "  OpenRouter rejected that key (HTTP $CODE, ${#OR_KEY} chars). Try pasting again." >&2
done
GROQ_KEY=$(ask "Groq API key for voice notes (press Enter to skip)") || GROQ_KEY=""
ALERT=$(askv "Safeguarding alert WhatsApp number, digits only e.g. 2778... (Enter to skip)")

# Reuse the DB password if the database was already created with it.
if [ -f "$H/db.env" ]; then
  PG=$(sed -n 's/^POSTGRES_PASSWORD=//p' "$H/db.env")
else
  PG=$(openssl rand -hex 24)
  printf 'POSTGRES_PASSWORD=%s\n' "$PG" > "$H/db.env"
fi

STT=stub; [ -n "$GROQ_KEY" ] && STT=groq
{
  printf 'WHATSAPP_ACCESS_TOKEN=%s\n' "$TOKEN"
  printf 'OPENROUTER_API_KEY=%s\n' "$OR_KEY"
  [ -n "$GROQ_KEY" ] && printf 'GROQ_API_KEY=%s\n' "$GROQ_KEY"
  printf 'STT_PROVIDER=%s\n' "$STT"
  [ -n "$ALERT" ] && printf 'SAFEGUARDING_ALERT_PHONE=%s\n' "${ALERT#+}"
  printf 'DATABASE_URL=postgresql://katlego:%s@db:5432/katlego\n' "$PG"
} > "$H/secrets.env"
chmod 600 "$H/secrets.env" "$H/db.env"

echo "Saved $H/secrets.env (token ${#TOKEN} chars, OpenRouter ${#OR_KEY} chars, voice notes: $STT, safeguarding alert: $([ -n "$ALERT" ] && echo set || echo "not set"))."
[ -f "$H/aws.env" ] && echo "AWS key file present." || echo "Still needed: $H/aws.env (written from CloudShell)."
