from __future__ import annotations

import os
from dataclasses import asdict, dataclass


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


@dataclass(frozen=True)
class LLMRefinementConfig:
    enabled: bool = False
    provider: str = "disabled"
    model: str = "qwen2.5vl:7b"
    base_url: str = "http://127.0.0.1:11434"
    api_key: str = "EMPTY"
    use_vision: bool = False
    only_low_confidence: bool = True
    max_formulas_per_doc: int = 5
    max_contexts_per_doc: int = 10
    min_confidence_to_apply: float = 0.75
    timeout_sec: int = 20
    context_window_sentences: int = 2
    max_image_side: int = 768
    max_crop_count: int = 5
    demo_mock: bool = False
    fail_open: bool = True
    skip_in_batch: bool = True


def get_llm_config() -> LLMRefinementConfig:
    provider = os.getenv("FG_LLM_PROVIDER", "disabled").strip().lower() or "disabled"
    demo_mock = _bool_env("FG_LLM_DEMO_MOCK", False)
    enabled = _bool_env("FG_ENABLE_LLM_REFINEMENT", False)
    if demo_mock and provider == "disabled":
        provider = "mock"
        enabled = True
    return LLMRefinementConfig(
        enabled=enabled,
        provider=provider,
        model=os.getenv("FG_LLM_MODEL", "qwen2.5vl:7b"),
        base_url=os.getenv("FG_LLM_BASE_URL", "http://127.0.0.1:11434"),
        api_key=os.getenv("FG_LLM_API_KEY", "EMPTY"),
        use_vision=_bool_env("FG_LLM_USE_VISION", False),
        only_low_confidence=_bool_env("FG_LLM_ONLY_LOW_CONFIDENCE", True),
        max_formulas_per_doc=_int_env("FG_LLM_MAX_FORMULAS_PER_DOC", 5),
        max_contexts_per_doc=_int_env("FG_LLM_MAX_CONTEXTS_PER_DOC", 10),
        min_confidence_to_apply=_float_env("FG_LLM_MIN_CONFIDENCE_TO_APPLY", 0.75),
        timeout_sec=_int_env("FG_LLM_TIMEOUT_SEC", 20),
        context_window_sentences=_int_env("FG_LLM_CONTEXT_WINDOW_SENTENCES", 2),
        max_image_side=_int_env("FG_LLM_MAX_IMAGE_SIDE", 768),
        max_crop_count=_int_env("FG_LLM_MAX_CROP_COUNT", 5),
        demo_mock=demo_mock,
        fail_open=_bool_env("FG_LLM_FAIL_OPEN", True),
        skip_in_batch=_bool_env("FG_LLM_SKIP_IN_BATCH", True),
    )


def get_llm_status() -> dict[str, object]:
    from .client import get_provider

    config = get_llm_config()
    if not config.enabled or config.provider == "disabled":
        return {
            **asdict(config),
            "available": False,
            "reason": "disabled",
        }
    provider = get_provider(config)
    available, reason = provider.is_available()
    return {
        **asdict(config),
        "available": available,
        "reason": "ok" if available else reason,
    }
