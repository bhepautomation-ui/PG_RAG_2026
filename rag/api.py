#!/usr/bin/env python3
from typing import List, Optional

from fastapi import FastAPI
from pydantic import BaseModel, Field

from ingest import count_source_chunks, delete_source_chunks, ingest_pending_files


class IngestRequest(BaseModel):
    files: Optional[List[str]] = Field(default=None, description="Optional list of file names from pending folder")
    replace_existing: bool = Field(default=True, description="Delete existing chunks for same source before insert")


app = FastAPI(title="PG_RAG_2026 API", version="0.1.0")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/ingest")
def ingest(req: IngestRequest) -> dict:
    result = ingest_pending_files(target_files=req.files, replace_existing=req.replace_existing)
    return {
        "files_processed": result.files_processed,
        "chunks_indexed": result.chunks_indexed,
        "deleted_rows": result.deleted_rows,
        "moved_files": result.moved_files,
    }


@app.get("/source/{source_name}/count")
def source_count(source_name: str) -> dict:
    return {"source": source_name, "chunk_count": count_source_chunks(source_name)}


@app.delete("/source/{source_name}")
def source_delete(source_name: str) -> dict:
    deleted = delete_source_chunks(source_name)
    return {"source": source_name, "deleted_rows": deleted}
