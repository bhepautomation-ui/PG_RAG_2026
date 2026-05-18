#!/usr/bin/env python3
import hashlib
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Iterable, List

import requests
from pypdf import PdfReader
from qdrant_client import QdrantClient
from qdrant_client.http import models as rest

PENDING_DIR = Path("shared/rag-files/pending")
PROCESSED_DIR = Path("shared/rag-files/processed")
QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "pg_rag_2026")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")
CHUNK_SIZE = int(os.getenv("RAG_CHUNK_SIZE", "900"))
CHUNK_OVERLAP = int(os.getenv("RAG_CHUNK_OVERLAP", "150"))


def read_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".txt", ".md"}:
        return path.read_text(encoding="utf-8", errors="ignore")
    if suffix == ".pdf":
        pages = []
        reader = PdfReader(str(path))
        for page in reader.pages:
            pages.append(page.extract_text() or "")
        return "\n".join(pages)
    raise ValueError(f"Unsupported file type: {path.suffix}")


def chunk_text(text: str, chunk_size: int, overlap: int) -> List[str]:
    cleaned = " ".join(text.split())
    if not cleaned:
        return []

    chunks: List[str] = []
    start = 0
    while start < len(cleaned):
        end = min(start + chunk_size, len(cleaned))
        chunks.append(cleaned[start:end])
        if end == len(cleaned):
            break
        start = max(0, end - overlap)
    return chunks


def embed(text: str) -> List[float]:
    response = requests.post(
        f"{OLLAMA_BASE_URL}/api/embeddings",
        json={"model": OLLAMA_EMBED_MODEL, "prompt": text},
        timeout=120,
    )
    response.raise_for_status()
    body = response.json()
    return body["embedding"]


def ensure_collection(client: QdrantClient, vector_size: int) -> None:
    collections = {c.name for c in client.get_collections().collections}
    if QDRANT_COLLECTION not in collections:
        client.create_collection(
            collection_name=QDRANT_COLLECTION,
            vectors_config=rest.VectorParams(size=vector_size, distance=rest.Distance.COSINE),
        )


def stable_id(source: str, chunk_index: int, chunk: str) -> int:
    digest = hashlib.sha1(f"{source}:{chunk_index}:{chunk}".encode("utf-8")).hexdigest()
    return int(digest[:15], 16)


def iter_supported_files(directory: Path) -> Iterable[Path]:
    for path in sorted(directory.glob("*")):
        if path.is_file() and path.suffix.lower() in {".txt", ".md", ".pdf"}:
            yield path


def main() -> None:
    PENDING_DIR.mkdir(parents=True, exist_ok=True)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    files = list(iter_supported_files(PENDING_DIR))
    if not files:
        print("No files found in shared/rag-files/pending")
        return

    print(f"Found {len(files)} file(s) to process")
    client = QdrantClient(url=QDRANT_URL)

    points = []
    for file_path in files:
        text = read_text(file_path)
        chunks = chunk_text(text, CHUNK_SIZE, CHUNK_OVERLAP)
        print(f"- {file_path.name}: {len(chunks)} chunks")

        for idx, chunk in enumerate(chunks):
            vector = embed(chunk)
            points.append(
                rest.PointStruct(
                    id=stable_id(file_path.name, idx, chunk),
                    vector=vector,
                    payload={
                        "source": file_path.name,
                        "chunk_index": idx,
                        "text": chunk,
                    },
                )
            )

    if not points:
        print("No chunks created. Nothing to index.")
        return

    ensure_collection(client, len(points[0].vector))
    client.upsert(collection_name=QDRANT_COLLECTION, points=points, wait=True)
    print(f"Indexed {len(points)} chunk(s) to collection '{QDRANT_COLLECTION}'")

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    for file_path in files:
        destination = PROCESSED_DIR / f"{timestamp}-{file_path.name}"
        shutil.move(str(file_path), destination)

    print("Moved processed files to shared/rag-files/processed")


if __name__ == "__main__":
    main()
