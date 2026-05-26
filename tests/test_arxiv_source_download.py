from __future__ import annotations

from backend.formula_graph.config import settings
from backend.formula_graph.ingestion import arxiv_source


def test_arxiv_source_download_is_attempted_before_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "sources_dir", tmp_path / "sources")
    cached = settings.sources_dir / "old_doc" / "2605.02988v1" / "extracted"
    cached.mkdir(parents=True)
    (cached / "main.tex").write_text("cached", encoding="utf-8")
    calls = []

    def fake_download(url: str) -> bytes:
        calls.append(url)
        return b"fresh"

    monkeypatch.setattr(arxiv_source, "_download", fake_download)

    source_dir, warnings = arxiv_source.fetch_arxiv_source("2605.02988v1", "new_doc")

    assert calls == ["https://arxiv.org/e-print/2605.02988v1"]
    assert warnings == []
    assert source_dir is not None
    assert (source_dir / "source.tex").read_text(encoding="utf-8") == "fresh"


def test_arxiv_source_cache_is_only_download_failure_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "sources_dir", tmp_path / "sources")
    cached = settings.sources_dir / "old_doc" / "2605.02988v1" / "extracted"
    cached.mkdir(parents=True)
    (cached / "main.tex").write_text("cached", encoding="utf-8")

    def fail_download(_url: str) -> bytes:
        raise OSError("network unavailable")

    monkeypatch.setattr(arxiv_source, "_download", fail_download)

    source_dir, warnings = arxiv_source.fetch_arxiv_source("2605.02988v1", "new_doc")

    assert source_dir is not None
    assert (source_dir / "main.tex").read_text(encoding="utf-8") == "cached"
    assert any("Не удалось скачать свежий TeX-источник" in warning for warning in warnings)
    assert any("локально кэшированный TeX-источник" in warning for warning in warnings)
