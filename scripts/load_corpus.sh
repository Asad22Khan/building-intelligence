#!/bin/sh
# Story 2.2: load sections, chunks, embeddings and the vector index into Atlas (~40 min first run).
# Usage: scripts/load_corpus.sh [--batch-size 8] [--delay 20] [--no-embed]
cd "$(dirname "$0")/.." || exit 1
[ -f .env ] || { echo ".env not found. Copy .env.example to .env first." >&2; exit 1; }
exec uv run python -m building_with_rag.load_corpus "$@"
