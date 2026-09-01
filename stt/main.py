"""Local speech-to-text service — faster-whisper on CPU, no API key.

The model (default: base, ~145MB) downloads from Hugging Face on first start
and is cached in the whisper-cache volume. faster-whisper decodes OGG/Opus
(WhatsApp voice notes) and browser WebM/MP4 directly via PyAV.
"""

import os
import tempfile

from fastapi import FastAPI, UploadFile
from faster_whisper import WhisperModel

MODEL_NAME = os.environ.get("WHISPER_MODEL", "base")

app = FastAPI(title="Katlego STT")
model: WhisperModel | None = None


@app.on_event("startup")
def load_model():
    global model
    model = WhisperModel(MODEL_NAME, device="cpu", compute_type="int8")


@app.get("/health")
def health():
    return {"ok": True, "model": MODEL_NAME}


@app.post("/transcribe")
async def transcribe(file: UploadFile):
    blob = await file.read()
    with tempfile.NamedTemporaryFile(suffix=".audio") as tmp:
        tmp.write(blob)
        tmp.flush()
        segments, info = model.transcribe(tmp.name, language="en", beam_size=5)
        text = " ".join(s.text.strip() for s in segments)
    return {"text": text, "language": info.language, "duration": info.duration}
