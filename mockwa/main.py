"""Mock WhatsApp Cloud (Graph) API.

Mimics the endpoints Katlego uses so the whole stack runs with zero Meta
credentials. The real WhatsAppClient talks to this container simply because
GRAPH_API_BASE_URL points here. Extra local-only endpoints:

  GET  /outbox            — captured outbound sends (tests + demo UI poll this)
  DELETE /outbox          — clear captured sends
  POST /media             — upload media (the demo UI's voice notes / photos)
  POST /block/{to}        — make the next send to that number fail once
"""

import itertools
import time
import uuid

from fastapi import FastAPI, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

app = FastAPI(title="Mock WhatsApp Cloud API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

OUTBOX: list[dict] = []
BLOCKED: set[str] = set()  # numbers whose next send fails once (POST /block/{to})
MEDIA: dict[str, tuple[bytes, str]] = {}
_counter = itertools.count(1)


@app.post("/{version}/{phone_number_id}/messages")
async def send_message(version: str, phone_number_id: str, payload: dict):
    if payload.get("to") in BLOCKED:
        # Like the real API outside the 24-hour customer service window.
        BLOCKED.discard(payload["to"])
        return JSONResponse({"error": {"code": 131047, "message": "Re-engagement message"}},
                            status_code=400)
    OUTBOX.append(
        {
            "index": len(OUTBOX),
            "to": payload.get("to", ""),
            "type": payload.get("type", "text"),
            "body": payload.get("text", {}).get("body", ""),
            "timestamp": time.time(),
        }
    )
    return {
        "messaging_product": "whatsapp",
        "contacts": [{"input": payload.get("to", ""), "wa_id": payload.get("to", "")}],
        "messages": [{"id": f"wamid.mock.{next(_counter)}"}],
    }


@app.post("/block/{to}")
async def block_next_send(to: str):
    BLOCKED.add(to)
    return {"blocked": to}


@app.get("/outbox")
async def outbox(to: str | None = None, since: int = 0):
    messages = [m for m in OUTBOX[since:] if to is None or m["to"] == to]
    return {"messages": messages, "next": len(OUTBOX)}


@app.delete("/outbox")
async def clear_outbox():
    OUTBOX.clear()
    return {"cleared": True}


@app.post("/media")
async def upload_media(file: UploadFile):
    media_id = uuid.uuid4().hex
    MEDIA[media_id] = (await file.read(), file.content_type or "application/octet-stream")
    return {"id": media_id}


@app.get("/media/{media_id}")
async def download_media(media_id: str):
    if media_id not in MEDIA:
        return JSONResponse({"error": "not found"}, status_code=404)
    blob, mime = MEDIA[media_id]
    return Response(content=blob, media_type=mime)


# Graph-API-shaped media metadata lookup: GET /v20.0/{media_id}
@app.get("/{version}/{media_id}")
async def media_info(version: str, media_id: str):
    if media_id not in MEDIA:
        return JSONResponse({"error": "not found"}, status_code=404)
    _, mime = MEDIA[media_id]
    return {
        "id": media_id,
        "mime_type": mime,
        "url": f"http://mockwa:8001/media/{media_id}",
    }
