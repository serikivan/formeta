from __future__ import annotations

from backend.formula_graph.llm.config import LLMRefinementConfig
from backend.formula_graph.llm.providers.openai_compatible_provider import OpenAICompatibleProvider


class VLLMProvider(OpenAICompatibleProvider):
    def __init__(self, config: LLMRefinementConfig) -> None:
        super().__init__(config)

    @property
    def provider_name(self) -> str:
        return "vllm"
