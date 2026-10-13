#!/bin/sh
# Story 2.3 checks (compact output only). Usage: scripts/verify_story_2_3.sh [--question "..."] [--no-query]
cd "$(dirname "$0")/.." || exit 1
exec uv run python -m building_with_rag.verify_semantic "$@"
