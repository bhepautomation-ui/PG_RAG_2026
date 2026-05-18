.PHONY: setup up down logs ingest ask

setup:
	python3 -m venv .venv
	. .venv/bin/activate && pip install --upgrade pip && pip install -r rag/requirements.txt
	cp -n .env.example .env || true

up:
	docker compose --profile cpu up -d

down:
	docker compose down

logs:
	docker compose logs -f --tail=100

ingest:
	. .venv/bin/activate && python rag/ingest.py

ask:
	@if [ -z "$(q)" ]; then \
		echo 'Usage: make ask q="pertanyaan"'; \
		exit 1; \
	fi
	. .venv/bin/activate && python rag/query.py "$(q)"
