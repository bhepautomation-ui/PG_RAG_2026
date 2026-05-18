#!/usr/bin/env python3
import os
import sys
from typing import List

import requests
from qdrant_client import QdrantClient

QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "pg_rag_2026")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")
OLLAMA_CHAT_MODEL = os.getenv("OLLAMA_CHAT_MODEL", "llama3.2")
TOP_K = int(os.getenv("RAG_TOP_K", "5"))


def embed(text: str) -> List[float]:
    response = requests.post(
        f"{OLLAMA_BASE_URL}/api/embeddings",
        json={"model": OLLAMA_EMBED_MODEL, "prompt": text},
        timeout=120,
    )
    response.raise_for_status()
    return response.json()["embedding"]


def generate(prompt: str) -> str:
    response = requests.post(
        f"{OLLAMA_BASE_URL}/api/generate",
        json={
            "model": OLLAMA_CHAT_MODEL,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.2},
        },
        timeout=240,
    )
    response.raise_for_status()
    return response.json()["response"]


def main() -> None:
    if len(sys.argv) < 2:
        print('Usage: python rag/query.py "pertanyaan anda"')
        sys.exit(1)

    question = " ".join(sys.argv[1:]).strip()
    client = QdrantClient(url=QDRANT_URL)

    query_vector = embed(question)
    hits = client.search(
        collection_name=QDRANT_COLLECTION,
        query_vector=query_vector,
        limit=TOP_K,
        with_payload=True,
    )

    if not hits:
        print("Tidak ada konteks ditemukan. Jalankan ingest dulu.")
        return

    contexts = []
    sources = []
    for i, hit in enumerate(hits, start=1):
        payload = hit.payload or {}
        source = payload.get("source", "unknown")
        text = payload.get("text", "")
        sources.append(f"[{i}] {source} (score={hit.score:.4f})")
        contexts.append(f"Sumber {i} ({source}):\n{text}")

    prompt = (
        "Kamu adalah asisten RAG. Jawab hanya berdasarkan konteks berikut. "
        "Jika informasi tidak ada di konteks, jawab tidak tahu.\n\n"
        f"KONTEKS:\n{'\n\n'.join(contexts)}\n\n"
        f"PERTANYAAN: {question}\n\n"
        "Jawaban ringkas dan jelas dalam Bahasa Indonesia."
    )

    answer = generate(prompt)
    print("\n=== JAWABAN ===\n")
    print(answer.strip())
    print("\n=== SUMBER ===")
    for item in sources:
        print(item)


if __name__ == "__main__":
    main()
