#!/usr/bin/env bash
# Run ON the server (Lightsail browser SSH):  sudo bash deploy/set-secrets.sh
# Asks for each secret with hidden typing and writes /opt/katlego/secrets.env
# and db.env (root only, mode 600). Nothing is echoed or logged.
set -euo pipefail
H=/opt/katlego
mkdir -p "$H"
umask 077

ask() { local v; read -r -s -p "$1: " v </dev/tty; echo >&2; printf '%s' "$v"; }
askv() { local v; read -r -p "$1: " v </dev/tty; printf '%s' "$v"; }

TOKEN=$(ask "Katlego Bot WhatsApp token (the never-expiring one)")
[ "${#TOKEN}" -ge 100 ] || { echo "That token looks too short (${#TOKEN} chars). Nothing written." >&2; exit 1; }
OR_KEY=$(ask "OpenRouter API key")
[ "${#OR_KEY}" -ge 20 ] || { echo "OpenRouter key looks too short. Nothing written." >&2; exit 1; }
GROQ_KEY=$(ask "Groq API key for voice notes (press Enter to skip)")
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

echo "Saved $H/secrets.env (token ${#TOKEN} chars, OpenRouter ${#OR_KEY} chars, voice notes: $STT, safeguarding alert: ${ALERT:+set}${ALERT:-not set})."
[ -f "$H/aws.env" ] && echo "AWS key file present." || echo "Still needed: $H/aws.env (written from CloudShell)."
