# Pinned to 3.12 for wheel coverage (host interpreter version is irrelevant —
# everything runs in containers).
FROM python:3.12-slim

WORKDIR /srv

COPY pyproject.toml README.md ./
COPY app ./app
COPY mockwa ./mockwa
COPY seed ./seed
COPY evals ./evals
COPY tests ./tests

RUN pip install --no-cache-dir ".[test]"
