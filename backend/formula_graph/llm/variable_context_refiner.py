from __future__ import annotations


def summarize_variable_context(*_, **__) -> dict[str, object]:
    return {"status": "skipped", "reason": "optional LLM variable context refinement is disabled by default"}
