"""WhatsApp Cloud API client.

The same client serves both environments: GRAPH_API_BASE_URL points at the
mockwa container locally and at https://graph.facebook.com in production —
no code changes to go live, only .env values.
"""

import httpx

from app.config import settings

API_VERSION = "v20.0"


class WhatsAppClient:
    def __init__(self) -> None:
        self.base_url = settings.graph_api_base_url.rstrip("/")
        self.phone_number_id = settings.whatsapp_phone_number_id
        self.headers = {"Authorization": f"Bearer {settings.whatsapp_access_token}"}

    async def send_text(self, to: str, body: str) -> dict:
        url = f"{self.base_url}/{API_VERSION}/{self.phone_number_id}/messages"
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "text",
            "text": {"preview_url": False, "body": body},
        }
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, json=payload, headers=self.headers)
            resp.raise_for_status()
            return resp.json()

    async def get_media(self, media_id: str) -> tuple[bytes, str]:
        """Resolve a media id to (bytes, mime_type) — two-step, as in the real API."""
        async with httpx.AsyncClient(timeout=60) as client:
            meta = await client.get(
                f"{self.base_url}/{API_VERSION}/{media_id}", headers=self.headers
            )
            meta.raise_for_status()
            info = meta.json()
            blob = await client.get(info["url"], headers=self.headers)
            blob.raise_for_status()
            mime = info.get("mime_type") or blob.headers.get(
                "content-type", "application/octet-stream"
            )
            return blob.content, mime
