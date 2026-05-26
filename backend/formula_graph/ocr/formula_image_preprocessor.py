from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image, ImageChops, ImageOps


def preprocess_formula_crop(crop_path: str | Path, output_path: str | Path | None = None) -> dict[str, Any]:
    source = Path(crop_path)
    warnings: list[str] = []
    if output_path is None:
        output = source.with_name(f"{source.stem}.preprocessed.png")
    else:
        output = Path(output_path)

    if not source.exists():
        return {"original_crop_path": str(source), "preprocessed_crop_path": None, "warnings": [f"Crop does not exist: {source}"]}

    try:
        with Image.open(source) as image:
            processed = ImageOps.grayscale(image)
            processed = _trim_white_margins(processed, warnings)
            processed = ImageOps.expand(processed, border=8, fill=255)
            processed = ImageOps.autocontrast(processed, cutoff=1)
            if min(processed.size) < 36:
                scale = max(2, int(36 / max(1, min(processed.size))))
                processed = processed.resize((processed.width * scale, processed.height * scale), Image.Resampling.LANCZOS)
            output.parent.mkdir(parents=True, exist_ok=True)
            processed.save(output)
    except Exception as exc:
        return {
            "original_crop_path": str(source),
            "preprocessed_crop_path": None,
            "warnings": [f"Formula crop preprocessing failed: {str(exc).splitlines()[0][:180]}"],
        }

    return {"original_crop_path": str(source), "preprocessed_crop_path": str(output), "warnings": warnings}


def _trim_white_margins(image: Image.Image, warnings: list[str]) -> Image.Image:
    background = Image.new(image.mode, image.size, 255)
    diff = ImageChops.difference(image, background)
    bbox = diff.point(lambda pixel: 255 if pixel > 12 else 0).getbbox()
    if bbox is None:
        warnings.append("Crop appears blank after preprocessing.")
        return image
    x0, y0, x1, y1 = bbox
    if x1 - x0 < 4 or y1 - y0 < 4:
        warnings.append("Crop content is very small; original crop kept.")
        return image
    return image.crop(bbox)
