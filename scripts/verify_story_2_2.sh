#!/bin/sh
# Story 2.2 checks. Usage: scripts/verify_story_2_2.sh [--section bns:103] [--question "..."]
cd "$(dirname "$0")/.." || exit 1
exec uv run python -m building_with_rag.verify_corpus "$@"
