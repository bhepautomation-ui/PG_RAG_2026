#!/usr/bin/env python3
import os
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, List, Sequence

import psycopg
import requests
from pgvector.psycopg import register_vector
from pypdf import PdfReader

PENDING_DIR = Path("shared/rag-files/pending")
PROCESSED_DIR = Path("shared/rag-files/processed")

SUPABASE_DB_HOST = os.getenv("SUPABASE_DB_HOST", "localhost")
SUPABASE_DB_PORT = int(os.getenv("SUPABASE_DB_PORT", "54322"))
SUPABASE_DB_NAME = os.getenv("SUPABASE_DB_NAME", "postgres")
SUPABASE_DB_USER = os.getenv("SUPABASE_DB_USER", "supabase_admin")
SUPABASE_DB_PASSWORD = os.getenv("SUPABASE_DB_PASSWORD", "postgres")
SUPABASE_TABLE = os.getenv("SUPABASE_TABLE", "rag_chunks")

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")
CHUNK_SIZE = int(os.getenv("RAG_CHUNK_SIZE", "900"))
CHUNK_OVERLAP = int(os.getenv("RAG_CHUNK_OVERLAP", "150"))


@dataclass
class IngestResult:
    files_processed: int
    chunks_indexed: int
    deleted_rows: int
    moved_files: List[str]


def ollama_base_candidates() -> List[str]:
    bases = [OLLAMA_BASE_URL]
    if "localhost" in OLLAMA_BASE_URL:
        bases.extend(
            [
                OLLAMA_BASE_URL.replace("localhost", "127.0.0.1"),
                OLLAMA_BASE_URL.replace("localhost", "[::1]"),
            ]
        )

    seen = set()
    ordered = []
    for item in bases:
        if item not in seen:
            ordered.append(item)
            seen.add(item)
    return ordered


def db_conn() -> psycopg.Connection:
    conn = psycopg.connect(
        host=SUPABASE_DB_HOST,
        port=SUPABASE_DB_PORT,
        dbname=SUPABASE_DB_NAME,
        user=SUPABASE_DB_USER,
        password=SUPABASE_DB_PASSWORD,
        autocommit=True,
    )
    register_vector(conn)
    return conn


def ensure_schema(conn: psycopg.Connection, vector_size: int) -> None:
    with conn.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {SUPABASE_TABLE} (
                id BIGSERIAL PRIMARY KEY,
                source TEXT NOT NULL,
                chunk_index INTEGER NOT NULL,
                content TEXT NOT NULL,
                embedding VECTOR({vector_size}) NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                UNIQUE(source, chunk_index)
            )
            """
        )
        cur.execute(
            f"""
            CREATE INDEX IF NOT EXISTS {SUPABASE_TABLE}_embedding_ivfflat
            ON {SUPABASE_TABLE}
            USING ivfflat (embedding vector_cosine_ops)
            WITH (lists = 100)
            """
        )


def count_source_chunks(source_name: str) -> int:
    conn = db_conn()
    try:
        with conn.cursor() as cur:
            try:
                cur.execute(
                    f"SELECT COUNT(*) FROM {SUPABASE_TABLE} WHERE source = %s",
                    (source_name,),
                )
                row = cur.fetchone()
                return int(row[0]) if row else 0
            except psycopg.errors.UndefinedTable:
                return 0
    finally:
        conn.close()


def delete_source_chunks(source_name: str) -> int:
    conn = db_conn()
    try:
        with conn.cursor() as cur:
            try:
                cur.execute(
                    f"DELETE FROM {SUPABASE_TABLE} WHERE source = %s",
                    (source_name,),
                )
                return cur.rowcount
            except psycopg.errors.UndefinedTable:
                return 0
    finally:
        conn.close()


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
    candidates = [OLLAMA_EMBED_MODEL]
    if ":" not in OLLAMA_EMBED_MODEL:
        candidates.append(f"{OLLAMA_EMBED_MODEL}:latest")

    for base_url in ollama_base_candidates():
        for model_name in candidates:
            response = requests.post(
                f"{base_url}/api/embed",
                json={"model": model_name, "input": text},
                timeout=120,
            )
            if response.status_code == 404:
                legacy = requests.post(
                    f"{base_url}/api/embeddings",
                    json={"model": model_name, "prompt": text},
                    timeout=120,
                )
                if legacy.status_code == 404:
                    continue
                legacy.raise_for_status()
                return legacy.json()["embedding"]

            response.raise_for_status()
            body = response.json()
            embeddings = body.get("embeddings", [])
            if embeddings:
                return embeddings[0]

    raise ValueError("No working embedding model found in Ollama")


def iter_supported_files(directory: Path) -> Iterable[Path]:
    for path in sorted(directory.glob("*")):
        if path.is_file() and path.suffix.lower() in {".txt", ".md", ".pdf"}:
            yield path


def _resolve_files(target_files: Sequence[str] | None) -> List[Path]:
    if target_files:
        files = [PENDING_DIR / Path(file_name).name for file_name in target_files]
        return [path for path in files if path.exists() and path.is_file()]
    return list(iter_supported_files(PENDING_DIR))


def ingest_pending_files(target_files: Sequence[str] | None = None, replace_existing: bool = True) -> IngestResult:
    PENDING_DIR.mkdir(parents=True, exist_ok=True)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    files = _resolve_files(target_files)
    if not files:
        return IngestResult(files_processed=0, chunks_indexed=0, deleted_rows=0, moved_files=[])

    rows = []
    for file_path in files:
        text = read_text(file_path)
        chunks = chunk_text(text, CHUNK_SIZE, CHUNK_OVERLAP)
        for idx, chunk in enumerate(chunks):
            rows.append((file_path.name, idx, chunk, embed(chunk)))

    if not rows:
        return IngestResult(files_processed=len(files), chunks_indexed=0, deleted_rows=0, moved_files=[])

    deleted_rows = 0
    conn = db_conn()
    try:
        ensure_schema(conn, len(rows[0][3]))
        with conn.cursor() as cur:
            if replace_existing:
                for file_path in files:
                    cur.execute(
                        f"DELETE FROM {SUPABASE_TABLE} WHERE source = %s",
                        (file_path.name,),
                    )
                    deleted_rows += cur.rowcount

            cur.executemany(
                f"""
                INSERT INTO {SUPABASE_TABLE} (source, chunk_index, content, embedding)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (source, chunk_index)
                DO UPDATE SET
                    content = EXCLUDED.content,
                    embedding = EXCLUDED.embedding,
                    updated_at = NOW()
                """,
                rows,
            )
            cur.execute(f"ANALYZE {SUPABASE_TABLE}")
    finally:
        conn.close()

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    moved_files: List[str] = []
    for file_path in files:
        destination = PROCESSED_DIR / f"{timestamp}-{file_path.name}"
        shutil.move(str(file_path), destination)
        moved_files.append(destination.name)

    return IngestResult(
        files_processed=len(files),
        chunks_indexed=len(rows),
        deleted_rows=deleted_rows,
        moved_files=moved_files,
    )


def main() -> None:
    result = ingest_pending_files(target_files=None, replace_existing=True)
    if result.files_processed == 0:
        print("No files found in shared/rag-files/pending")
        return

    print(f"Found {result.files_processed} file(s) to process")
    print(f"Deleted {result.deleted_rows} existing chunk(s) due to dedup replace mode")
    print(f"Indexed {result.chunks_indexed} chunk(s) to Supabase table '{SUPABASE_TABLE}'")
    print("Moved processed files to shared/rag-files/processed")


if __name__ == "__main__":
    main()
