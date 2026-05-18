# PG_RAG_2026

RAG (Retrieval-Augmented Generation) local yang dibangun dengan acuan:
[theaiautomators/self-hosted-ai-starter-kit](https://github.com/theaiautomators/self-hosted-ai-starter-kit).

Proyek ini berisi:
- Stack Docker: `n8n + Ollama + Supabase Postgres (pgvector) + PostgreSQL + Docling + static file server`
- Integrasi opsional `n8n-mcp` untuk akses MCP ke dokumentasi dan manajemen workflow n8n
- Script RAG Python untuk:
  - ingest dokumen (`txt`, `md`, `pdf`) ke Supabase lokal
  - query tanya-jawab berbasis konteks dokumen

## 1) Prasyarat

- Docker + Docker Compose
- Python 3.10+

## 2) Setup cepat

```bash
cp .env.example .env
make setup
make up
```

Service utama:
- n8n: <http://localhost:5678>
- Ollama API: <http://localhost:11434>
- Supabase Postgres: `localhost:${SUPABASE_DB_PORT:-54322}`
- Docling: <http://localhost:5001>
- Static file server: <http://localhost:8080>
- n8n-mcp (opsional): <http://localhost:3000/mcp>

## 3) Ingest dokumen ke knowledge base

Taruh file di:
- `shared/rag-files/pending/`

Format yang didukung:
- `.txt`, `.md`, `.pdf`

Lalu jalankan:

```bash
make ingest
```

Hasil:
- Chunk dokumen masuk ke tabel Supabase `rag_chunks` (default)
- File dipindahkan ke `shared/rag-files/processed/`

## 4) Tanya RAG

```bash
make ask q="Apa isi utama dokumen yang sudah diupload?"
```

Script akan:
- buat embedding pertanyaan via Ollama (`nomic-embed-text`)
- ambil konteks teratas dari Supabase (pgvector similarity)
- generate jawaban via Ollama (`llama3.2`)
- tampilkan sumber chunk yang dipakai

## 5) Konfigurasi environment

Atur variabel berikut di `.env` jika perlu:

```env
SUPABASE_DB_HOST=localhost
SUPABASE_DB_PORT=54322
SUPABASE_DB_NAME=postgres
SUPABASE_DB_USER=supabase_admin
SUPABASE_DB_PASSWORD=postgres
SUPABASE_TABLE=rag_chunks
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_EMBED_MODEL=nomic-embed-text
OLLAMA_CHAT_MODEL=llama3.2
RAG_CHUNK_SIZE=900
RAG_CHUNK_OVERLAP=150
RAG_TOP_K=5
```

## 6) Struktur penting

- `docker-compose.yml` - stack infrastruktur lokal
- `rag/ingest.py` - indexing dokumen ke Supabase (pgvector)
- `rag/query.py` - retrieval + generation dari Supabase
- `rag/requirements.txt` - dependensi Python
- `shared/rag-files/pending/` - folder input dokumen
- `shared/rag-files/processed/` - arsip dokumen terproses

## 7) Menjalankan n8n-mcp (opsional)

`n8n-mcp` dipakai kalau kita ingin agent/LLM mengakses tools khusus n8n via MCP.

1. Pastikan token di `.env` sudah diisi:

```env
N8N_MCP_AUTH_TOKEN=replace-with-32-char-minimum-token
N8N_MCP_PORT=3000
N8N_API_KEY= # opsional, untuk workflow management
```

2. Jalankan stack dengan profile MCP:

```bash
make up-mcp
```

3. Endpoint MCP yang dipakai client:

```text
http://localhost:${N8N_MCP_PORT:-3000}/mcp
```

4. Header auth yang dibutuhkan:

```text
Authorization: Bearer <N8N_MCP_AUTH_TOKEN>
```

Catatan:
- `N8N_API_KEY` opsional. Tanpa ini, `n8n-mcp` tetap bisa dipakai untuk dokumentasi/validasi node.
- Untuk manajemen workflow (create/update/execute), isi `N8N_API_KEY` dari n8n.

## 8) Publish ke GitHub (repo: PG_RAG_2026)

Jika belum login GitHub CLI:

```bash
gh auth login
```

Lalu:

```bash
git init
git add .
git commit -m "feat: bootstrap PG_RAG_2026 from self-hosted AI starter kit"
git branch -M main
gh repo create PG_RAG_2026 --public --source=. --remote=origin --push
```

Jika ingin private, ganti `--public` menjadi `--private`.

## Kredit

- Base template: [theaiautomators/self-hosted-ai-starter-kit](https://github.com/theaiautomators/self-hosted-ai-starter-kit)
- Original upstream: [n8n-io/self-hosted-ai-starter-kit](https://github.com/n8n-io/self-hosted-ai-starter-kit)
- n8n-mcp: [czlonkowski/n8n-mcp](https://github.com/czlonkowski/n8n-mcp)
