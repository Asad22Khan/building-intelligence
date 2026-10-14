import json
import time
import uuid
from collections.abc import Iterator

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import ValidationError

from .contracts import (
    ChatCompletionChoice,
    ChatCompletionChunk,
    ChatCompletionChunkChoice,
    ChatCompletionDelta,
    ChatCompletionMessage,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ModelCard,
    ModelList,
    OpenAIErrorBody,
    OpenAIErrorEnvelope,
    QueryRequest,
    QueryResult,
    SemanticFilters,
)
from .generation import Event
from .patterns import run_pattern, run_pattern_events
from .registry import MODE_MODEL_IDS, MODEL_ID_MODES
from .settings import get_settings

app = FastAPI(title="Building with RAG")


class OpenAIError(Exception):
    def __init__(
        self,
        status_code: int,
        message: str,
        param: str | None = None,
        code: str | None = None,
    ):
        self.status_code = status_code
        self.body = OpenAIErrorBody(
            message=message, type="invalid_request_error", param=param, code=code
        )


def _error_response(status_code: int, body: OpenAIErrorBody) -> JSONResponse:
    return JSONResponse(
        status_code=status_code, content=OpenAIErrorEnvelope(error=body).model_dump()
    )


@app.exception_handler(OpenAIError)
async def _openai_error(_: Request, exc: OpenAIError) -> JSONResponse:
    return _error_response(exc.status_code, exc.body)


@app.exception_handler(RequestValidationError)
async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    errors = exc.errors()
    if request.url.path == "/v1/chat/completions":
        first = errors[0] if errors else {}
        loc = ".".join(str(p) for p in first.get("loc", []) if p != "body")
        return _error_response(
            400,
            OpenAIErrorBody(
                message=f"Invalid request: {first.get('msg', 'validation failed')}",
                type="invalid_request_error",
                param=loc or None,
            ),
        )
    return JSONResponse(
        status_code=422, content={"detail": json.loads(json.dumps(errors, default=str))}
    )


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/v1/query", response_model=QueryResult)
def query(request: QueryRequest) -> QueryResult:
    return run_pattern(request)


@app.get("/v1/models", response_model=ModelList)
def models() -> ModelList:
    return ModelList(data=[ModelCard(id=m) for m in MODE_MODEL_IDS.values()])


def _to_query_request(body: ChatCompletionRequest) -> QueryRequest:
    mode = MODEL_ID_MODES.get(body.model)
    if mode is None:
        raise OpenAIError(
            404,
            f"The model '{body.model}' does not exist.",
            param="model",
            code="model_not_found",
        )
    options = body.rag_options
    if options and options.pattern and options.pattern != mode:
        raise OpenAIError(
            400,
            "rag_options.pattern does not match the selected model.",
            param="rag_options.pattern",
        )
    user_messages = [m for m in body.messages if m.role == "user"]
    if not user_messages:
        raise OpenAIError(400, "At least one user message is required.", param="messages")
    fields: dict = {"question": user_messages[-1].content, "pattern": mode}
    if options:
        if options.limit is not None:
            fields["limit"] = options.limit
        fields["required_acts"] = options.required_acts
        fields["chapter"] = options.chapter
        if options.act or options.status or options.access_level:
            fields["filters"] = SemanticFilters(
                act=options.act, status=options.status, access_level=options.access_level
            )
    # Identity and generation settings are server-side only; never taken from the browser.
    fields["caller_id"] = get_settings().webui_demo_caller_id
    fields["generate_answer"] = True
    try:
        return QueryRequest(**fields)
    except ValidationError as exc:
        raise OpenAIError(
            400, "The question must be 1-4,000 characters.", param="messages"
        ) from exc


def _stream(completion_id: str, created: int, model: str, events: Iterator[Event]) -> Iterator[str]:
    def frame(delta: ChatCompletionDelta, finish: str | None = None) -> str:
        chunk = ChatCompletionChunk(
            id=completion_id,
            created=created,
            model=model,
            choices=[ChatCompletionChunkChoice(delta=delta, finish_reason=finish)],
        )
        return f"data: {chunk.model_dump_json(exclude_none=True)}\n\n"

    yield frame(ChatCompletionDelta(role="assistant"))
    try:
        for kind, payload in events:
            if kind == "text" and payload:
                yield frame(ChatCompletionDelta(content=payload))
    except Exception:  # never leave the stream open or leak details
        yield frame(ChatCompletionDelta(content="\n\nUNAVAILABLE — the answer was interrupted."))
    yield frame(ChatCompletionDelta(), finish="stop")
    yield "data: [DONE]\n\n"


@app.post("/v1/chat/completions")
def chat_completions(body: ChatCompletionRequest):
    # Same dispatch path as /v1/query. Retrieval runs here, before any text is streamed.
    events = run_pattern_events(_to_query_request(body))
    completion_id = f"chatcmpl-{uuid.uuid4().hex}"
    created = int(time.time())
    if body.stream:
        return StreamingResponse(
            _stream(completion_id, created, body.model, events),
            media_type="text/event-stream",
        )
    text = "".join(payload for kind, payload in events if kind == "text")
    return ChatCompletionResponse(
        id=completion_id,
        created=created,
        model=body.model,
        choices=[ChatCompletionChoice(message=ChatCompletionMessage(content=text))],
    )
