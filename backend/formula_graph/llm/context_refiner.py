from __future__ import annotations

from backend.formula_graph.llm.schemas import ContextRefinementRequest, ContextRefinementResult


def refine_context(request: ContextRefinementRequest) -> ContextRefinementResult:
    return ContextRefinementResult(
        formula_id=request.formula_id,
        context_summary="",
        warnings=["Context refinement is optional and disabled unless a provider is explicitly enabled."],
    )
