from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.formula_graph.postprocessing.text_cleaner import clean_ocr_text


class OCRFallback:
    def __init__(self, engine: str = "none") -> None:
        self.engine = (engine or "none").lower().strip()

    def recognize_page(self, image_path: str) -> dict[str, Any]:
        path = Path(image_path)
        if self.engine == "none":
            return _result("", "none", 0.0, ["OCR fallback disabled."])
        if self.engine == "mock":
            return _result(path.stem, "mock", 0.5, [])
        if not path.exists():
            return _result("", self.engine, 0.0, [f"Image does not exist: {image_path}"])
        if self.engine == "tesseract":
            return self._recognize_tesseract(path)
        if self.engine == "paddleocr":
            return self._recognize_paddle(path)
        return _result("", self.engine, 0.0, [f"Unsupported OCR fallback engine: {self.engine}"])

    def recognize_document(self, rendered_pages: list[dict[str, Any]]) -> dict[str, Any]:
        pages: list[dict[str, Any]] = []
        warnings: list[str] = []
        for page in rendered_pages:
            image_path = str(page.get("image_path") or page.get("path") or "")
            result = self.recognize_page(image_path)
            result["page_number"] = page.get("page_number") or page.get("page") or len(pages) + 1
            pages.append(result)
            warnings.extend(result.get("warnings", []))
        text = "\n\n".join(page.get("text", "") for page in pages if page.get("text"))
        return {"engine": self.engine, "text": text, "pages": pages, "warnings": warnings}

    def _recognize_tesseract(self, path: Path) -> dict[str, Any]:
        try:
            import pytesseract
            from PIL import Image

            with Image.open(path) as image:
                text = pytesseract.image_to_string(image)
            return _result(clean_ocr_text(text), "tesseract", 0.65, [])
        except Exception as exc:
            return _result("", "tesseract", 0.0, [f"Tesseract OCR unavailable: {_short_error(exc)}"])

    def _recognize_paddle(self, path: Path) -> dict[str, Any]:
        try:
            from paddleocr import PaddleOCR

            ocr = PaddleOCR(use_angle_cls=True, lang="en")
            raw = ocr.ocr(str(path), cls=True)
            lines: list[str] = []
            for page in raw or []:
                for item in page or []:
                    if len(item) >= 2 and isinstance(item[1], (list, tuple)) and item[1]:
                        lines.append(str(item[1][0]))
            return _result(clean_ocr_text("\n".join(lines)), "paddleocr", 0.7, [])
        except Exception as exc:
            return _result("", "paddleocr", 0.0, [f"PaddleOCR fallback unavailable: {_short_error(exc)}"])


def _result(text: str, engine: str, confidence: float, warnings: list[str]) -> dict[str, Any]:
    return {"text": text, "engine": engine, "confidence": confidence, "warnings": warnings}


def _short_error(exc: Exception) -> str:
    return str(exc).splitlines()[0][:180]
