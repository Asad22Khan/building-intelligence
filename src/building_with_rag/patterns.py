"""Pattern dispatch. Modes without their own story stay honest placeholders."""

from .contracts import QueryRequest, QueryResult
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


def run_pattern(request: QueryRequest, *, retrieve: bool = True) -> QueryResult:
    """`retrieve=False` keeps chat a placeholder until answer generation exists."""
    if request.pattern == "semantic" and retrieve:
        from .semantic import run_semantic

        result = run_semantic(request)
        if request.generate_answer:
            from .generation import add_generation

            return add_generation(request, result)  # same evidence, no second retrieval
        return result
    return placeholder(request)
