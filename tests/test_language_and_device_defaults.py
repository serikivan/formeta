from backend.formula_graph.config import settings
from backend.formula_graph.models import TextBlock
from backend.formula_graph.pipeline import detect_ocr_language


def test_default_device_prefers_gpu_with_runtime_fallback():
    assert settings.device == "gpu"


def test_default_ocr_language_is_auto():
    assert settings.ocr_lang == "auto"


def test_detect_ocr_language_uses_cyrillic_ratio():
    blocks = [
        TextBlock(
            id="tb_1",
            page_number=1,
            text="Математическая модель распространения загрязнения атмосферы города является актуальной задачей. "
            "В работе используется численный метод и параллельная реализация.",
            source="pdf_text_layer",
        )
    ]

    assert detect_ocr_language(blocks) == "ru"


def test_detect_ocr_language_uses_latin_ratio():
    blocks = [
        TextBlock(
            id="tb_1",
            page_number=1,
            text="In this paper we consider a numerical method for formula recognition and knowledge graph construction.",
            source="pdf_text_layer",
        )
    ]

    assert detect_ocr_language(blocks) == "en"
