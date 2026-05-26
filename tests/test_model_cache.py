from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from backend.formula_graph.ocr.formula_recognition import FormulaRecognitionAdapter
from backend.formula_graph.ocr.model_cache import clear_model_cache
from backend.formula_graph.ocr.paddle_structure import PaddleStructureAdapter
from backend.formula_graph.ocr.paddle_text import PaddleOCRAdapter


@pytest.fixture(autouse=True)
def reset_model_cache():
    clear_model_cache()
    yield
    clear_model_cache()


def test_paddle_structure_engine_is_cached_across_adapter_instances(monkeypatch):
    created: list[object] = []

    class FakePPStructureV3:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            created.append(self)

    monkeypatch.setitem(sys.modules, "paddleocr", SimpleNamespace(PPStructureV3=FakePPStructureV3))

    first = PaddleStructureAdapter(device="cpu").engine
    second = PaddleStructureAdapter(device="cpu").engine

    assert first is second
    assert len(created) == 1
    assert created[0].kwargs["device"] == "cpu"


def test_paddle_ocr_engine_is_cached_by_device_lang_and_version(monkeypatch):
    created: list[object] = []

    class FakePaddleOCR:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            created.append(self)

    monkeypatch.setitem(sys.modules, "paddleocr", SimpleNamespace(PaddleOCR=FakePaddleOCR))

    first = PaddleOCRAdapter(device="cpu", lang="en").engine
    second = PaddleOCRAdapter(device="cpu", lang="en").engine
    third = PaddleOCRAdapter(device="cpu", lang="ru").engine

    assert first is second
    assert first is not third
    assert len(created) == 2
    assert created[0].kwargs["ocr_version"] == "PP-OCRv5"
    assert created[1].kwargs["ocr_version"] == "PP-OCRv3"


def test_formula_recognition_engine_is_cached_across_adapter_instances(monkeypatch):
    created: list[object] = []

    class FakeFormulaRecognition:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            created.append(self)

    monkeypatch.setitem(sys.modules, "paddleocr", SimpleNamespace(FormulaRecognition=FakeFormulaRecognition))

    first = FormulaRecognitionAdapter(device="cpu").engine
    second = FormulaRecognitionAdapter(device="cpu").engine

    assert first is second
    assert len(created) == 1
    assert created[0].kwargs["model_name"] == "PP-FormulaNet_plus-L"
