from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.formula_graph.config import ensure_directories
from backend.formula_graph.ocr.paddle_structure import PaddleStructureAdapter
from backend.formula_graph.ocr.paddle_text import PaddleOCRAdapter


def main() -> int:
    parser = argparse.ArgumentParser(description="Initialize and download OCR models.")
    parser.add_argument("--lite", action="store_true", help="Only initialize the default text OCR model.")
    args = parser.parse_args()

    ensure_directories()
    print("Initializing PaddleOCR text model...")
    try:
        _ = PaddleOCRAdapter().engine
        print("PaddleOCR text model is ready.")
    except Exception as exc:
        print(f"PaddleOCR initialization failed: {exc}")
        return 1

    if not args.lite:
        print("Initializing PPStructureV3 with formula recognition...")
        try:
            _ = PaddleStructureAdapter().engine
            print("PPStructureV3/formula models are ready.")
        except Exception as exc:
            print(f"PPStructureV3 initialization failed: {exc}")
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
