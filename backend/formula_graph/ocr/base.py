from __future__ import annotations

from abc import ABC, abstractmethod

from backend.formula_graph.models import FormulaBlock, PageImage, TextBlock


class OCRAdapter(ABC):
    name: str

    @abstractmethod
    def recognize_pages(self, pages: list[PageImage], progress_callback=None) -> tuple[list[TextBlock], list[str]]:
        """Return text blocks and non-fatal warnings."""


class StructureAdapter(ABC):
    name: str

    @abstractmethod
    def parse_pages(self, pages: list[PageImage], progress_callback=None) -> tuple[list[TextBlock], list[FormulaBlock], list[str]]:
        """Return text blocks, formulas and non-fatal warnings."""
