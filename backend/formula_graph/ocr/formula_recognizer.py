from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.formula_graph.ocr.formula_image_preprocessor import preprocess_formula_crop
from backend.formula_graph.postprocessing.latex_cleaner import build_latex_variants


class FormulaRecognizer:
    def __init__(self, engine: str = "mock_text_layer") -> None:
        self.engine = (engine or "mock_text_layer").strip()

    def recognize_formula(
        self,
        formula_id: str,
        *,
        text_layer: str = "",
        crop_path: str | Path | None = None,
        raw_latex: str | None = None,
        confidence: float = 0.72,
    ) -> dict[str, Any]:
        warnings: list[str] = []
        preprocessed_crop_path = None
        if crop_path:
            preprocessing = preprocess_formula_crop(crop_path)
            warnings.extend(preprocessing.get("warnings", []))
            preprocessed_crop_path = preprocessing.get("preprocessed_crop_path")

        raw = raw_latex if raw_latex is not None else text_layer
        variants = build_latex_variants(raw)
        return {
            "formula_id": formula_id,
            "text_layer": text_layer,
            "raw_latex": variants["raw_latex"],
            "cleaned_latex": variants["cleaned_latex"],
            "normalized_latex": variants["normalized_latex"],
            "plain_formula_text": variants["plain_formula_text"],
            "recognition_engine": self.engine,
            "recognition_confidence": confidence,
            "preprocessed_crop_path": preprocessed_crop_path,
            "warnings": [*warnings, *variants["sanity"].get("warnings", [])],
        }


def build_formula_recognition_record(
    formula_id: str,
    text_layer: str = "",
    raw_latex: str | None = None,
    recognition_engine: str = "mock_text_layer",
    recognition_confidence: float = 0.72,
) -> dict[str, Any]:
    return FormulaRecognizer(recognition_engine).recognize_formula(
        formula_id,
        text_layer=text_layer,
        raw_latex=raw_latex,
        confidence=recognition_confidence,
    )
