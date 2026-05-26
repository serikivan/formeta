from __future__ import annotations

import json
import shlex
import subprocess
import sys
from functools import cached_property
from pathlib import Path
from typing import Any

from PIL import Image

from backend.formula_graph.config import resolve_device, settings
from backend.formula_graph.models import PageImage, TextBlock
from backend.formula_graph.ocr.base import OCRAdapter


class GotOCRAdapter(OCRAdapter):
    name = "got_ocr"

    def __init__(
        self,
        device: str | None = None,
        model: str | None = None,
        command: str | None = None,
        max_new_tokens: int | None = None,
    ) -> None:
        self.device = resolve_device(device)
        self.model_name = model or settings.got_ocr_model
        self.command = command or settings.got_ocr_command
        self.max_new_tokens = max_new_tokens or settings.got_ocr_max_new_tokens

    @cached_property
    def _model_bundle(self) -> tuple[Any, Any] | None:
        if not self.model_name:
            return None
        try:
            from transformers import AutoModelForImageTextToText, AutoProcessor

            processor = AutoProcessor.from_pretrained(self.model_name, trust_remote_code=True)
            model = AutoModelForImageTextToText.from_pretrained(self.model_name, trust_remote_code=True)
            if hasattr(model, "eval"):
                model = model.eval()
            if self.device == "gpu" and hasattr(model, "to"):
                model = model.to("cuda")
            return model, processor
        except Exception:
            return None

    def recognize_pages(self, pages: list[PageImage], progress_callback=None) -> tuple[list[TextBlock], list[str]]:
        blocks: list[TextBlock] = []
        warnings: list[str] = []
        if not pages:
            return blocks, warnings

        if self._command_args():
            return self._recognize_with_command(pages, progress_callback=progress_callback)

        if self._model_bundle is None:
            return [], ["GOT-OCR is not configured: set FG_GOT_OCR_COMMAND or FG_GOT_OCR_MODEL."]

        model, processor = self._model_bundle
        total = max(1, len(pages))
        for index, page in enumerate(pages, start=1):
            try:
                text = self._run_model(model, processor, page.image_path)
                page_blocks = _blocks_from_text(page, text, self.name)
                if page_blocks:
                    blocks.extend(page_blocks)
                else:
                    warnings.append(f"GOT-OCR вернул пустой текст на странице {page.page_number}.")
            except Exception as exc:
                warnings.append(f"GOT-OCR завершился ошибкой на странице {page.page_number}: {exc}")
            if progress_callback is not None:
                progress_callback(index, total)
        return blocks, warnings

    def _recognize_with_command(self, pages: list[PageImage], progress_callback=None) -> tuple[list[TextBlock], list[str]]:
        blocks: list[TextBlock] = []
        warnings: list[str] = []
        total = max(1, len(pages))
        for index, page in enumerate(pages, start=1):
            try:
                text = self._run_command(page.image_path)
                page_blocks = _blocks_from_text(page, text, self.name)
                if page_blocks:
                    blocks.extend(page_blocks)
                else:
                    warnings.append(f"Команда GOT-OCR вернула пустой текст на странице {page.page_number}.")
            except Exception as exc:
                warnings.append(f"Команда GOT-OCR завершилась ошибкой на странице {page.page_number}: {exc}")
            if progress_callback is not None:
                progress_callback(index, total)
        return blocks, warnings

    def _run_command(self, image_path: str) -> str:
        completed = subprocess.run(
            [*self._command_args(), image_path],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        output = completed.stdout.strip()
        if not output:
            return ""
        if output.startswith("{") or output.startswith("["):
            try:
                payload = json.loads(output)
                text = _extract_text(payload)
                if text:
                    return text
            except Exception:
                pass
        return output

    def _run_model(self, model: Any, processor: Any, image_path: str) -> str:
        image = Image.open(Path(image_path)).convert("RGB")
        if hasattr(model, "generate"):
            try:
                inputs = processor(images=image, return_tensors="pt")
                if self.device == "gpu":
                    inputs = {key: value.to("cuda") if hasattr(value, "to") else value for key, value in inputs.items()}
                outputs = model.generate(
                    **inputs,
                    max_new_tokens=self.max_new_tokens,
                )
                if hasattr(processor, "batch_decode"):
                    decoded = processor.batch_decode(outputs, skip_special_tokens=True)
                    if decoded:
                        return decoded[0].strip()
                if hasattr(processor, "decode"):
                    sequence = outputs[0] if isinstance(outputs, (list, tuple)) else outputs[0]
                    return str(processor.decode(sequence, skip_special_tokens=True)).strip()
                return _extract_text(outputs)
            except Exception as exc:
                raise RuntimeError(f"GOT-OCR generic generate() path failed: {exc}") from exc

        if hasattr(model, "chat"):
            try:
                result = model.chat(
                    processor,
                    image,
                    ocr_type="ocr",
                    max_new_tokens=self.max_new_tokens,
                )
            except TypeError:
                result = model.chat(processor, image, ocr_type="ocr")
            return _extract_text(result)

        raise RuntimeError("Configured GOT-OCR model exposes neither generate() nor chat().")

    def _command_args(self) -> list[str]:
        if self.command:
            return shlex.split(self.command, posix=False)
        runner = _default_runner_script()
        if runner is not None and self.model_name:
            return [
                sys.executable,
                str(runner),
                "--model",
                self.model_name,
                "--device",
                self.device,
                "--max-new-tokens",
                str(self.max_new_tokens),
            ]
        return []


def _blocks_from_text(page: PageImage, text: str, source: str) -> list[TextBlock]:
    normalized = "\n".join(line.rstrip() for line in str(text).splitlines()).strip()
    if not normalized:
        return []
    lines = [line.strip() for line in normalized.splitlines() if line.strip()]
    if not lines:
        lines = [normalized]
    height = (page.height * 72) / max(1, page.dpi)
    width = (page.width * 72) / max(1, page.dpi)
    line_height = max(10.0, height / max(1, len(lines)))
    blocks: list[TextBlock] = []
    for index, line in enumerate(lines, start=1):
        y0 = min(height - 1, (index - 1) * line_height)
        y1 = min(height, y0 + line_height)
        blocks.append(
            TextBlock(
                id=f"p{page.page_number}_got_{index}",
                page_number=page.page_number,
                text=line,
                bbox=(0.0, y0, width, y1),
                source="got_ocr",
                confidence=0.62,
            )
        )
    return blocks


def _extract_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        for key in ("text", "ocr_text", "generated_text", "result", "content"):
            item = value.get(key)
            if isinstance(item, str) and item.strip():
                return item.strip()
        for item in value.values():
            text = _extract_text(item)
            if text:
                return text
        return ""
    if isinstance(value, list):
        parts = [_extract_text(item) for item in value]
        return "\n".join(part for part in parts if part).strip()
    return str(value).strip() if value is not None else ""


def _default_runner_script() -> Path | None:
    candidate = Path(__file__).resolve().parents[3] / "scripts" / "got_ocr_runner.py"
    return candidate if candidate.exists() else None
