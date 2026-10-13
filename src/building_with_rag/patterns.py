"""Pattern dispatch. Every mode is an honest placeholder until its story lands."""

from .contracts import QueryRequest, QueryResult
from .registry import MODE_MODEL_IDS


def run_pattern(request: QueryRequest) -> QueryResult:
    return QueryResult(
        pattern=request.pattern,
        status="not_implemented",
        message=(
            f"The '{request.pattern}' pattern ({MODE_MODEL_IDS[request.pattern]}) "
            "is not implemented yet."
        ),
        trace=[f"pattern={request.pattern}", "placeholder"],
    )
