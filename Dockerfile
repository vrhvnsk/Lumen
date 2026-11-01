# Lumen: one image that contains the API, the website and a ready-built search index.
#
#   docker build -t lumen .
#   docker run -p 8000:7860 lumen            # then open http://localhost:8000
#
# Smaller/cheaper hosts: use the small embedding model (about 80 MB instead of 420 MB):
#   docker build --build-arg EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2 -t lumen .
#
# The index is built while the image is built (needs internet to download the
# model once), so the container starts in seconds.

FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/app/.hf-cache

RUN useradd --create-home --uid 1000 app
WORKDIR /app

# CPU-only PyTorch first: the default wheel pulls in gigabytes of GPU libraries we never use.
RUN pip install torch --index-url https://download.pytorch.org/whl/cpu
COPY backend/requirements.txt backend/requirements.txt
RUN pip install -r backend/requirements.txt

COPY backend backend
COPY frontend frontend

ARG EMBEDDING_MODEL=sentence-transformers/all-mpnet-base-v2
ENV EMBEDDING_MODEL=${EMBEDDING_MODEL}

WORKDIR /app/backend
RUN python build_index.py && chown -R app:app /app

USER app
ENV PORT=7860
EXPOSE 7860

# --proxy-headers: trust X-Forwarded-* from the reverse proxy in front of the container.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips '*'"]
