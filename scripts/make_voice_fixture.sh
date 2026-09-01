#!/usr/bin/env bash
# Generate the spoken-audio E2E fixture (macOS `say` + ffmpeg → OGG/Opus,
# the same codec WhatsApp uses for voice notes).
set -euo pipefail

cd "$(dirname "$0")/.."
mkdir -p tests/fixtures

TEXT="How do I factorise x squared plus five x plus six?"
TMP_AIFF=$(mktemp -t katlego-voice).aiff

say -o "$TMP_AIFF" "$TEXT"
ffmpeg -y -loglevel error -i "$TMP_AIFF" -c:a libopus -b:a 24k tests/fixtures/voice_factorise.ogg
rm -f "$TMP_AIFF"

echo "Wrote tests/fixtures/voice_factorise.ogg ($(du -h tests/fixtures/voice_factorise.ogg | cut -f1))"
