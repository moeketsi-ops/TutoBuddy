"""Gateway: WhatsApp Cloud API webhook receiver.

Blueprint §4.2 — verify, dedupe, fast-ack. Webhooks must be ACKed in seconds
while the full STT → RAG → LLM pipeline can take 10–30s, so this service only
validates and enqueues; all reasoning happens in app/worker.py.
"""

import hashlib
import hmac
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Query, Request, Response
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse

from app.config import settings
from app.queue import STREAM, ensure_group, get_redis

log = logging.getLogger("katlego.gateway")
logging.basicConfig(level=logging.INFO)

DEDUPE_TTL_SECONDS = 7 * 24 * 3600
STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(_: FastAPI):
    await ensure_group()
    yield


app = FastAPI(title="Katlego Gateway", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"ok": True}


@app.get("/demo")
async def demo():
    return FileResponse(STATIC_DIR / "simulator.html")


@app.get("/webhook")
async def verify_webhook(
    mode: str = Query("", alias="hub.mode"),
    token: str = Query("", alias="hub.verify_token"),
    challenge: str = Query("", alias="hub.challenge"),
):
    # Meta's one-time webhook verification handshake.
    if mode == "subscribe" and token == settings.whatsapp_verify_token:
        return PlainTextResponse(challenge)
    return Response(status_code=403)


def _signature_ok(raw_body: bytes, header: str | None) -> bool:
    if not settings.is_set(settings.meta_app_secret):
        return True  # local/mock mode — no app secret configured yet
    if not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(
        settings.meta_app_secret.encode(), raw_body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, header.removeprefix("sha256="))


@app.post("/webhook")
async def receive_webhook(request: Request):
    raw = await request.body()
    if not _signature_ok(raw, request.headers.get("X-Hub-Signature-256")):
        return Response(status_code=403)

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return Response(status_code=400)

    r = get_redis()
    enqueued = 0
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            contacts = {
                c.get("wa_id"): c.get("profile", {}).get("name", "")
                for c in value.get("contacts", [])
            }
            for message in value.get("messages", []):
                msg_id = message.get("id", "")
                # Meta redelivers webhooks — dedupe on the WhatsApp message id.
                if msg_id and not await r.set(
                    f"dedupe:{msg_id}", 1, nx=True, ex=DEDUPE_TTL_SECONDS
                ):
                    log.info("duplicate webhook dropped: %s", msg_id)
                    continue
                job = {
                    "from": message.get("from", ""),
                    "name": contacts.get(message.get("from", ""), ""),
                    "message": message,
                }
                await r.xadd(STREAM, {"payload": json.dumps(job)})
                enqueued += 1

    # Always 200 fast — Meta disables webhooks that error or stall.
    return JSONResponse({"status": "received", "enqueued": enqueued})
