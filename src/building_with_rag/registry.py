"""Shared registry of course modes and their OpenAI-style model IDs."""

from typing import Literal

Mode = Literal["semantic", "hybrid", "hybrid-reranked", "structured", "decomposition", "hyde"]

MODE_MODEL_IDS: dict[str, str] = {
    "semantic": "rag-semantic",
    "hybrid": "rag-hybrid",
    "hybrid-reranked": "rag-hybrid-reranked",
    "structured": "rag-structured",
    "decomposition": "rag-decomposition",
    "hyde": "rag-hyde",
}

MODEL_ID_MODES: dict[str, str] = {v: k for k, v in MODE_MODEL_IDS.items()}
