FROM python:3.12-slim

WORKDIR /srv

# faster-whisper and PyAV are pinned together. faster-whisper (up to 1.2.1)
# calls av.open(..., metadata_errors="ignore"); PyAV 16+ removed that
# argument, so an unpinned rebuild pulled av 19 and every voice note failed
# with "TypeError: open() got an unexpected keyword argument
# 'metadata_errors'". av 15.1.0 is the newest release that still accepts it
# (checked 2026-10-06). Only raise these together, and re-run test_voice.py.
RUN pip install --no-cache-dir "faster-whisper==1.2.1" "av==15.1.0" \
    "fastapi>=0.115" "uvicorn>=0.30" "python-multipart>=0.0.9"

COPY main.py .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "9000"]
