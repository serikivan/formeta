from __future__ import annotations

from dataclasses import dataclass
from importlib.util import find_spec


@dataclass(frozen=True)
class ExperimentalBackendStatus:
    name: str
    installed: bool
    package: str
    role: str
    notes: str


def experimental_backend_statuses() -> list[ExperimentalBackendStatus]:
    return [
        ExperimentalBackendStatus(
            name="olmocr",
            installed=find_spec("olmocr") is not None,
            package="olmocr",
            role="text_ocr",
            notes="PDF/page linearization and reading-order fallback.",
        ),
        ExperimentalBackendStatus(
            name="got_ocr",
            installed=find_spec("transformers") is not None,
            package="transformers + stepfun-ai/GOT-OCR-2.0-hf",
            role="text_ocr",
            notes="Experimental-only page/region OCR via stepfun-ai/GOT-OCR-2.0-hf; not enabled in the default pipeline.",
        ),
        ExperimentalBackendStatus(
            name="deepseek_ocr",
            installed=find_spec("transformers") is not None or find_spec("vllm") is not None,
            package="transformers or vllm + DeepSeek-OCR model files",
            role="text_ocr",
            notes="Heavy page-to-markdown OCR candidate.",
        ),
        ExperimentalBackendStatus(
            name="pix2tex",
            installed=find_spec("pix2tex") is not None,
            package="pix2tex",
            role="formula_ocr",
            notes="Cropped formula image to LaTeX baseline.",
        ),
        ExperimentalBackendStatus(
            name="texify",
            installed=find_spec("texify") is not None,
            package="texify",
            role="formula_ocr",
            notes="Math-heavy page/image to Markdown and LaTeX.",
        ),
        ExperimentalBackendStatus(
            name="ollama",
            installed=find_spec("ollama") is not None,
            package="ollama",
            role="semantic_postprocess",
            notes="Local LLM client for structured JSON cleanup.",
        ),
    ]
