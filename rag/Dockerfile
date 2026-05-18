FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir -r /app/requirements.txt && pip install --no-cache-dir fastapi==0.115.6 uvicorn[standard]==0.32.1

COPY ingest.py /app/ingest.py
COPY query.py /app/query.py
COPY api.py /app/api.py

EXPOSE 8800

CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8800"]
