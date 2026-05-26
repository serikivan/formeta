from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.formula_graph.config import resolve_device


def main() -> int:
    try:
        import paddle
    except Exception as exc:
        print(f"Paddle import failed: {exc}")
        return 1

    print(f"Paddle version: {paddle.__version__}")
    print(f"Compiled with CUDA: {paddle.device.is_compiled_with_cuda()}")
    if paddle.device.is_compiled_with_cuda():
        print(f"CUDA device count: {paddle.device.cuda.device_count()}")
    else:
        print("CUDA device count: 0")
    print(f"Resolved backend device: {resolve_device()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
