"""Pattern dispatch. Modes without their own story stay honest placeholders."""

from collections.abc import Iterator

from .contracts import QueryRequest, QueryResult
from .generation import Event
from .registry import MODE_MODEL_IDS


def placeholder(request: QueryRequest) -> QueryResult:
    return QueryResult(
        pattern=request.pattern,
        status="not_implemented",
        message=(
            f"The '{request.pattern}' pattern ({MODE_MODEL_IDS[request.pattern]}) "
            "is not implemented yet."
        ),
        trace=[f"pattern={request.pattern}", "placeholder"],
    )


def run_pattern_events(request: QueryRequest) -> Iterator[Event]:
    """The one dispatch path. Retrieval runs now (once, not streamed); the returned events
    are the text to show and, last, the final QueryResult."""
    if request.pattern == "semantic":
        from .semantic import run_semantic

        result = run_semantic(request)
        if request.generate_answer:
            from .generation import generate_events

            return generate_events(request, result)  # same evidence, no second retrieval
        return iter([("text", result.message), ("result", result)])
    result = placeholder(request)
    return iter([("text", result.message), ("result", result)])


def run_pattern(request: QueryRequest) -> QueryResult:
    """Drain the events and return the final result (used by /v1/query)."""
    final = None
    for kind, payload in run_pattern_events(request):
        if kind == "result":
            final = payload
    return final
