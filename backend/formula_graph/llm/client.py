from __future__ import annotations

from typing import Protocol

from .config import LLMRefinementConfig
from .providers.mock_provider import MockProvider
from .providers.ollama_provider import OllamaProvider
from .providers.openai_compatible_provider import OpenAICompatibleProvider
from .providers.vllm_provider import VLLMProvider
from .schemas import FormulaVerificationRequest, FormulaVerificationResult


class LLMProvider(Protocol):
    def is_available(self) -> tuple[bool, str]: ...

    def verify_formula(self, request: FormulaVerificationRequest) -> FormulaVerificationResult: ...


def get_provider(config: LLMRefinementConfig) -> LLMProvider:
    if config.provider == "mock":
        return MockProvider(config)
    if config.provider == "ollama":
        return OllamaProvider(config)
    if config.provider == "vllm":
        return VLLMProvider(config)
    if config.provider == "openai_compatible":
        return OpenAICompatibleProvider(config)
    return MockProvider(config, disabled=True)
