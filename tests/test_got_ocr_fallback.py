from backend.formula_graph.config import settings
from backend.formula_graph.models import PageImage, TextBlock
from backend.formula_graph.pipeline import _recognize_text_from_pages


def _sample_page() -> PageImage:
    return PageImage(page_number=1, image_path="page.png", width=1000, height=1400, dpi=300)


def test_got_ocr_backend_setting_is_ignored(monkeypatch):
    monkeypatch.setattr(settings, "text_ocr_backend", "got_ocr")

    def fake_paddle(self, pages):
        return (
            [
                TextBlock(
                    id="p1_paddle_1",
                    page_number=1,
                    text="Paddle text",
                    bbox=(0, 0, 100, 20),
                    source="paddleocr",
                    confidence=0.7,
                )
            ],
            [],
        )

    monkeypatch.setattr("backend.formula_graph.ocr.paddle_text.PaddleOCRAdapter.recognize_pages", fake_paddle)

    blocks, warnings = _recognize_text_from_pages([_sample_page()], ocr_mode="auto", device_mode="cpu", ocr_lang="en")

    assert not warnings
    assert blocks[0].source == "paddleocr"
    assert blocks[0].text == "Paddle text"


def test_got_ocr_fallback_is_not_used(monkeypatch):
    monkeypatch.setattr(settings, "text_ocr_backend", "paddle")
    monkeypatch.setattr(settings, "enable_got_ocr_fallback", True)
    monkeypatch.setattr(settings, "got_ocr_command", "got-ocr-cli")

    def fake_paddle(self, pages):
        return [], ["PaddleOCR failed softly."]

    def fail_if_got_is_called(self, pages):
        raise AssertionError("GOT-OCR must not be used by the main OCR pipeline.")

    monkeypatch.setattr("backend.formula_graph.ocr.paddle_text.PaddleOCRAdapter.recognize_pages", fake_paddle)
    monkeypatch.setattr("backend.formula_graph.ocr.got_ocr_adapter.GotOCRAdapter.recognize_pages", fail_if_got_is_called)

    blocks, warnings = _recognize_text_from_pages([_sample_page()], ocr_mode="auto", device_mode="cpu", ocr_lang="en")

    assert blocks == []
    assert warnings == ["PaddleOCR failed softly."]
