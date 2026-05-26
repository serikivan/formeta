from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from PIL import Image


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a local GOT-OCR model on a page image and print OCR text.")
    parser.add_argument("image_path", help="Path to the page image.")
    parser.add_argument("--model", required=True, help="Transformers model id or local path for GOT-OCR.")
    parser.add_argument("--device", choices=("cpu", "gpu"), default="cpu", help="Execution device.")
    parser.add_argument("--max-new-tokens", type=int, default=2048, help="Maximum generated tokens.")
    parser.add_argument("--json", action="store_true", help="Print JSON payload instead of plain text.")
    args = parser.parse_args()

    image_path = Path(args.image_path)
    if not image_path.exists():
        print(f"Image not found: {image_path}", file=sys.stderr)
        return 2

    try:
        text = run_got_ocr(image_path, args.model, args.device, args.max_new_tokens)
    except Exception as exc:
        print(f"GOT-OCR runner failed: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps({"text": text}, ensure_ascii=False))
    else:
        print(text)
    return 0


def run_got_ocr(image_path: Path, model_name: str, device: str, max_new_tokens: int) -> str:
    from transformers import AutoModelForImageTextToText, AutoProcessor

    image = Image.open(image_path).convert("RGB")
    processor = AutoProcessor.from_pretrained(model_name, trust_remote_code=True)
    model = AutoModelForImageTextToText.from_pretrained(model_name, trust_remote_code=True)
    if hasattr(model, "eval"):
        model = model.eval()
    target_device = "cuda" if device == "gpu" else "cpu"
    if target_device == "cuda" and hasattr(model, "to"):
        model = model.to(target_device)

    if hasattr(model, "generate"):
        inputs = processor(images=image, return_tensors="pt")
        if target_device == "cuda":
            inputs = {key: value.to(target_device) if hasattr(value, "to") else value for key, value in inputs.items()}
        outputs = model.generate(**inputs, max_new_tokens=max_new_tokens)
        if hasattr(processor, "batch_decode"):
            decoded = processor.batch_decode(outputs, skip_special_tokens=True)
            if decoded:
                return decoded[0].strip()
        if hasattr(processor, "decode"):
            return str(processor.decode(outputs[0], skip_special_tokens=True)).strip()
        return extract_text(outputs)

    if hasattr(model, "chat"):
        try:
            result = model.chat(
                processor,
                image,
                ocr_type="ocr",
                max_new_tokens=max_new_tokens,
            )
        except TypeError:
            result = model.chat(processor, image, ocr_type="ocr")
        return extract_text(result)

    raise RuntimeError("Configured GOT-OCR model exposes neither generate() nor chat().")


def extract_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        for key in ("text", "ocr_text", "generated_text", "result", "content"):
            item = value.get(key)
            if isinstance(item, str) and item.strip():
                return item.strip()
        for item in value.values():
            text = extract_text(item)
            if text:
                return text
        return ""
    if isinstance(value, list):
        parts = [extract_text(item) for item in value]
        return "\n".join(part for part in parts if part).strip()
    return str(value).strip() if value is not None else ""


if __name__ == "__main__":
    raise SystemExit(main())
