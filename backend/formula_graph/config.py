import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FG_", env_file=".env", extra="ignore")

    project_root: Path = Path(__file__).resolve().parents[2]
    data_dir: Path = project_root / "data"
    input_dir: Path = data_dir / "input"
    processed_dir: Path = data_dir / "processed"
    results_dir: Path = data_dir / "results"
    models_dir: Path = data_dir / "models"
    sources_dir: Path = data_dir / "sources"

    render_dpi: int = 300
    structure_max_dpi: int = 200
    max_pages: int = 0
    ocr_lang: str = "auto"
    device: str = "gpu"
    text_ocr_backend: str = "paddle"
    formula_ocr_backend: str = "pp_formulanet"
    enable_got_ocr_fallback: bool = False
    got_ocr_model: str | None = "stepfun-ai/GOT-OCR-2.0-hf"
    got_ocr_command: str | None = None
    got_ocr_max_new_tokens: int = 4096
    enable_vlm_postprocess: bool = False
    vlm_postprocess_backend: str = "ollama"
    ollama_model: str = "qwen2.5:7b"
    enable_paddle: bool = True
    enable_formula_ocr: bool = True
    formula_ocr_max_refine_candidates: int = 96
    formula_ocr_parallel_preprocess_workers: int = 4
    formula_ocr_refine_confidence_threshold: float = 0.86
    storage_retention_days: int = 14
    storage_max_documents: int = 30
    storage_delete_input_after_processing: bool = True

    @property
    def all_dirs(self) -> list[Path]:
        return [self.input_dir, self.processed_dir, self.results_dir, self.models_dir, self.sources_dir]


settings = Settings()


def ensure_directories() -> None:
    for directory in settings.all_dirs:
        directory.mkdir(parents=True, exist_ok=True)


def configure_model_cache() -> None:
    ensure_directories()
    paddle_cache = settings.models_dir / "paddlex"
    paddle_cache.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("PADDLEX_HOME", str(paddle_cache))
    os.environ.setdefault("PADDLEX_CACHE_HOME", str(paddle_cache))
    os.environ.setdefault("PADDLEX_TEMP_DIR", str(paddle_cache / "temp"))
    os.environ.setdefault("PADDLE_PDX_CACHE_HOME", str(paddle_cache))
    os.environ.setdefault("PADDLE_HOME", str(settings.models_dir / "paddle"))
    os.environ.setdefault("HUGGINGFACE_HUB_CACHE", str(settings.models_dir / "huggingface"))
    os.environ.setdefault("TRANSFORMERS_CACHE", str(settings.models_dir / "huggingface"))
    os.environ.setdefault("HF_HOME", str(settings.models_dir / "huggingface"))
    os.environ.setdefault("TORCH_HOME", str(settings.models_dir / "torch"))
    windows_font = Path("C:/Windows/Fonts/arial.ttf")
    if windows_font.exists():
        os.environ.setdefault("PADDLE_PDX_LOCAL_FONT_FILE_PATH", str(windows_font))


configure_model_cache()


def resolve_device(device: str | None = None) -> str:
    configured = (device or settings.device).lower().strip()
    if configured == "cpu":
        return "cpu"
    if configured == "gpu":
        return "gpu" if _gpu_available() else "cpu"
    if configured == "auto":
        return "gpu" if _gpu_available() else "cpu"
    return "cpu"


def _gpu_available() -> bool:
    try:
        import paddle

        return bool(paddle.device.is_compiled_with_cuda() and paddle.device.cuda.device_count() > 0)
    except Exception:
        return False
