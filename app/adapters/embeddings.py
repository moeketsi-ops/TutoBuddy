"""Embeddings for RAG.

hash   — deterministic offline hashing embedder (no key, CI-safe). Good enough
         for a ~20-chunk seeded corpus; exercises the real pgvector path.
openai — text-embedding-3-small at EMBEDDING_DIM dims (placeholder key).
"""

import hashlib
import math
import re

import httpx

from app.config import settings


def _hash_embed(text: str, dim: int) -> list[float]:
    vec = [0.0] * dim
    tokens = re.findall(r"[a-z0-9]+", text.lower())
    grams = tokens + [f"{a} {b}" for a, b in zip(tokens, tokens[1:])]
    for gram in grams:
        h = int(hashlib.md5(gram.encode()).hexdigest(), 16)
        sign = 1.0 if (h >> 64) % 2 == 0 else -1.0
        vec[h % dim] += sign
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


async def embed(text: str) -> list[float]:
    if settings.embeddings_provider == "openai":
        if not settings.is_set(settings.openai_api_key):
            raise RuntimeError("EMBEDDINGS_PROVIDER=openai but OPENAI_API_KEY is a placeholder")
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "https://api.openai.com/v1/embeddings",
                headers={"Authorization": f"Bearer {settings.openai_api_key}"},
                json={
                    "model": "text-embedding-3-small",
                    "input": text,
                    "dimensions": settings.embedding_dim,
                },
            )
            resp.raise_for_status()
            return resp.json()["data"][0]["embedding"]
    return _hash_embed(text, settings.embedding_dim)
