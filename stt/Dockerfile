FROM python:3.12-slim

WORKDIR /srv

RUN pip install --no-cache-dir "faster-whisper>=1.0" "fastapi>=0.115" \
    "uvicorn>=0.30" "python-multipart>=0.0.9"

COPY main.py .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "9000"]
