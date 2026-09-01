"""Homework-photo pipeline: media fetch → vision reply (stub in keyless mode)."""

import base64

# Smallest valid 1x1 PNG.
PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGNgYGBgAAAABQAB"
    "h6FO1AAAAABJRU5ErkJggg=="
)


def test_photo_end_to_end(onboarded_chat):
    media_id = onboarded_chat.upload_media(PNG_1PX, "image/png")
    onboarded_chat.send(
        {"type": "image", "image": {"id": media_id, "mime_type": "image/png", "caption": ""}}
    )
    reply = onboarded_chat.wait_for_reply()
    # Stub mode acknowledges the photo; anthropic mode tutors on it.
    assert "photo" in reply.lower() or "?" in reply
