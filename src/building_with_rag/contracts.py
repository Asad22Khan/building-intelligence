"""Typed contracts. Models only, no behavior. Extend additively."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .registry import Mode

# ---------------------------------------------------------------- query contracts


class SemanticFilters(BaseModel):
    # Unknown fields, operators and caller-shaped MongoDB fragments are rejected.
    model_config = ConfigDict(extra="forbid")

    act: list[str] = Field(default_factory=list)
    status: list[str] = Field(default_factory=list)
    access_level: list[str] = Field(default_factory=list)


class QueryRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    pattern: Mode
    caller_id: str | None = None
    filters: SemanticFilters | None = None
    limit: int = Field(default=5, ge=1, le=20)
    generate_answer: bool = False
    required_acts: list[str] = Field(default_factory=list)
    chapter: str | None = None

    @field_validator("question")
    @classmethod
    def _question_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("question must not be blank")
        return value


class RetrievedChunk(BaseModel):
    chunk_id: str
    section_id: str
    act: str
    text: str
    heading: str | None = None
    score: float | None = None
    source: str | None = None
    source_url: str | None = None
    page: int | None = None
    chapter: str | None = None


class OmittedCandidate(BaseModel):
    chunk_id: str
    omitted_reason: str


class SubquestionEvidence(BaseModel):
    subquestion: str
    status: Literal["evidenced", "no_evidence"]
    results: list[RetrievedChunk] = Field(default_factory=list)
    reason: str | None = None


class StructuredSignals(BaseModel):
    intent: Literal["exact_lookup", "filter", "aggregation"]
    act: str | None = None
    section_number: str | None = None
    chapter: str | None = None


class GenerationResult(BaseModel):
    outcome: Literal["answered", "insufficient_evidence", "unavailable", "malformed"]
    answer: str | None = None
    claims: list[Any] = Field(default_factory=list)
    citations: list[Any] = Field(default_factory=list)
    supporting_passages: list[RetrievedChunk] = Field(default_factory=list)
    provider: str | None = None
    model: str | None = None
    trace: list[str] = Field(default_factory=list)
    context_outcome: str | None = None
    confidence: float | None = None
    draft_answer: str | None = None
    issues: list[str] = Field(default_factory=list)
    attempts: int | None = None
    low_confidence_reason: str | None = None


class QueryResult(BaseModel):
    pattern: str
    status: str
    message: str
    trace: list[str] = Field(default_factory=list)
    results: list[RetrievedChunk] = Field(default_factory=list)
    generation: GenerationResult | None = None
    omitted_candidates: list[OmittedCandidate] = Field(default_factory=list)
    subquestions: list[SubquestionEvidence] = Field(default_factory=list)
    hyde_direct_candidates: list[RetrievedChunk] = Field(default_factory=list)
    hyde_query_candidates: list[RetrievedChunk] = Field(default_factory=list)
    hyde_hypothetical_text_debug: str | None = None


# ---------------------------------------------------------------- OpenAI contracts


class RagOptions(BaseModel):
    """Options sent by the Open WebUI Pipe."""

    # Unknown keys from the Pipe are ignored (never used); the Pipe may add fields.
    model_config = ConfigDict(extra="ignore")

    pattern: Mode | None = None
    act: list[str] = Field(default_factory=list)
    status: list[str] = Field(default_factory=list)
    access_level: list[str] = Field(default_factory=list)
    limit: int | None = Field(default=None, ge=1, le=20)
    required_acts: list[str] = Field(default_factory=list)
    chapter: str | None = None

    @field_validator("act", "status", "access_level", "required_acts", mode="before")
    @classmethod
    def _none_means_empty(cls, value):
        # The Pipe may send null for "all" (no filter); treat it as an empty list.
        return [] if value is None else value


class ChatMessage(BaseModel):
    role: Literal["system", "developer", "user", "assistant"]
    content: str


class ChatCompletionRequest(BaseModel):
    model: str
    messages: list[ChatMessage] = Field(min_length=1)
    stream: bool = False
    n: int = Field(default=1, ge=1, le=1)
    rag_options: RagOptions | None = None


class ChatCompletionMessage(BaseModel):
    role: Literal["assistant"] = "assistant"
    content: str


class ChatCompletionChoice(BaseModel):
    index: int = 0
    message: ChatCompletionMessage
    finish_reason: str = "stop"


class Usage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class ChatCompletionResponse(BaseModel):
    id: str
    object: Literal["chat.completion"] = "chat.completion"
    created: int
    model: str
    choices: list[ChatCompletionChoice]
    usage: Usage = Field(default_factory=Usage)


class ChatCompletionDelta(BaseModel):
    role: Literal["assistant"] | None = None
    content: str | None = None


class ChatCompletionChunkChoice(BaseModel):
    index: int = 0
    delta: ChatCompletionDelta
    finish_reason: str | None = None


class ChatCompletionChunk(BaseModel):
    id: str
    object: Literal["chat.completion.chunk"] = "chat.completion.chunk"
    created: int
    model: str
    choices: list[ChatCompletionChunkChoice]


class ModelCard(BaseModel):
    id: str
    object: Literal["model"] = "model"
    created: int = 0
    owned_by: str = "building-with-rag"


class ModelList(BaseModel):
    object: Literal["list"] = "list"
    data: list[ModelCard]


class OpenAIErrorBody(BaseModel):
    message: str
    type: str
    param: str | None = None
    code: str | None = None


class OpenAIErrorEnvelope(BaseModel):
    error: OpenAIErrorBody


# ---------------------------------------------------------------- MongoDB schemas
# Typed models only; no database access in this story.


class SectionDocument(BaseModel):
    section_id: str  # act-qualified, e.g. "BNS-103"
    act: str
    section_number: str
    heading: str | None = None
    chapter: str | None = None
    text: str
    source: str | None = None
    status: str | None = None
    access_level: str | None = None
    # Story 2.2 additions (see mongodb_schema.py)
    source_id: str | None = None
    act_label: str | None = None
    chapter_title: str | None = None
    source_pdf: str | None = None
    source_sha256: str | None = None
    page_start: int | None = None
    page_end: int | None = None
    needs_review: bool | None = None


class ChunkDocument(BaseModel):
    chunk_id: str
    section_id: str
    act: str
    text: str
    heading: str | None = None
    source: str | None = None
    status: str | None = None
    access_level: str | None = None
    embedding: list[float] | None = None  # unused: vectors live in `embeddings` (Story 2.2)
    embedding_model: str = "voyage-3.5"
    embedding_version: str = "voyage-3.5"
    # Story 2.2 additions (see mongodb_schema.py)
    chunk_index: int | None = None
    chunking_version: str | None = None
    splitter: str | None = None
    embedding_input_text: str | None = None
    chapter: str | None = None
    text_sha256: str | None = None


class EmbeddingDocument(BaseModel):
    embedding_id: str
    chunk_id: str
    embedding_model: str
    embedding_version: str
    dimensions: int
    vector: list[float]
    act: str
    chapter: str
    status: str
    access_level: str
    input_sha256: str
