from __future__ import annotations

import json
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Callable

from PIL import Image

from backend.formula_graph.config import ensure_directories, settings
from backend.formula_graph.export.graph_ready_export import build_graph_ready_document, save_graph_ready_document
from backend.formula_graph.export.metagraph_metrics import compute_metagraph_metrics
from backend.formula_graph.export.structured_document import build_structured_document, save_structured_document
from backend.formula_graph.graph.builder import build_graph
from backend.formula_graph.graph.graph_ready_metagraph import (
    build_metagraph_from_graph_ready,
    metagraph_to_knowledge_graph,
    save_metagraph,
)
from backend.formula_graph.graph.demo_report import create_demo_summary
from backend.formula_graph.graph.metagraph_validator import validate_metagraph
from backend.formula_graph.graph.metagraph import build_metagraph
from backend.formula_graph.graph.semantic_metagraph import save_semantic_artifacts
from backend.formula_graph.graph.semantic_visualization import (
    generate_demo_dashboard,
    generate_formula_graph_view,
    generate_graph_view,
    generate_metagraph_view,
)
from backend.formula_graph.graph.visualization_export import export_visualization_payload
from backend.formula_graph.ingestion.arxiv_source import fetch_arxiv_source, normalize_arxiv_id
from backend.formula_graph.ingestion.loaders import persist_upload, render_document
from backend.formula_graph.ingestion.masking import mask_formula_regions, reconstruct_text_with_formula_tokens
from backend.formula_graph.layout.formulas import extract_formulas
from backend.formula_graph.layout.regions import (
    assign_formula_tokens,
    build_formula_regions,
    consolidate_assigned_formulas,
    merge_formula_candidates,
    reindex_formulas,
)
from backend.formula_graph.layout.tex_document import parse_tex_document
from backend.formula_graph.layout.tex_source import extract_tex_formulas
from backend.formula_graph.llm.formula_verifier import manual_refinement_step
from backend.formula_graph.models import FormulaBlock, FormulaRegion, PageImage, ProcessingResult, TextBlock
from backend.formula_graph.ocr.paddle_structure import PaddleStructureAdapter
from backend.formula_graph.ocr.paddle_text import PaddleOCRAdapter
from backend.formula_graph.ocr.formula_recognition import FormulaRecognitionAdapter
from backend.formula_graph.ocr.marker_adapter import MarkerAdapter
from backend.formula_graph.ocr.tesseract_text import TesseractOCRAdapter
from backend.formula_graph.postprocessing.formulas import (
    normalize_formula_blocks,
    reconcile_formula_candidates_with_text_layer,
    rescue_formula_definitions,
)
from backend.formula_graph.postprocessing.text import normalize_text_blocks
from backend.formula_graph.semantic.entities import bind_formulas_to_context, extract_entities
from backend.formula_graph.semantic.formula_interpreter import interpret_formula, interpret_formula_record
from backend.formula_graph.storage_cleanup import cleanup_after_processing


def process_document(
    source_path: Path,
    original_name: str,
    ocr_mode: str = "auto",
    device_mode: str = "gpu",
    ocr_lang: str | None = None,
    max_pages: int | None = None,
    render_dpi: int | None = None,
    arxiv_id: str | None = None,
    prefer_tex_source: bool = True,
    progress_callback: Callable[[float, str, str | None], None] | None = None,
    is_batch: bool = False,
) -> ProcessingResult:
    ensure_directories()
    total_started_at = time.perf_counter()
    stage_times: dict[str, float] = {}
    document_id, stored_path = persist_upload(source_path, original_name)
    warnings: list[str] = []
    max_pages = settings.max_pages if max_pages is None else max_pages
    render_dpi = render_dpi or settings.render_dpi
    if ocr_mode == "standard":
        if render_dpi > 220:
            warnings.append(f"Стандартный режим ограничил render_dpi до 220 вместо запрошенных {render_dpi}.")
            render_dpi = 220
        if not max_pages or max_pages <= 0:
            max_pages = 20
            warnings.append("Стандартный режим ограничил обработку 20 страницами; задайте max_pages явно или используйте расширенный OCR-режим для полной обработки.")
    structure_max_dpi = settings.structure_max_dpi
    requested_language = ocr_lang or settings.ocr_lang
    tex_id = normalize_arxiv_id(arxiv_id) or normalize_arxiv_id(original_name)

    try:
        if ocr_mode == "tex_source" or (prefer_tex_source and tex_id and stored_path.suffix.lower() == ".pdf"):
            tex_result = _try_process_tex_source(
                document_id=document_id,
                stored_path=stored_path,
                original_name=original_name,
                tex_id=tex_id,
                warnings=warnings,
                progress_callback=progress_callback,
            )
            if tex_result is not None:
                return _save_result_bundle(
                    tex_result,
                    "tex_source",
                    device_mode,
                    requested_language,
                    _resolve_ocr_language(requested_language, []),
                    "tex_source_selected_no_ocr",
                    render_dpi,
                    True,
                    progress_callback=progress_callback,
                    is_batch=is_batch,
                    stored_input_path=stored_path,
                )
            if ocr_mode == "tex_source":
                result = ProcessingResult(
                    document_id=document_id,
                    filename=original_name,
                    created_at=datetime.utcnow(),
                    status="partial",
                    warnings=warnings or ["Выбран режим TeX-источника, но TeX-источник недоступен."],
                )
                return _save_result_bundle(
                    result,
                    "tex_source",
                    device_mode,
                    requested_language,
                    _resolve_ocr_language(requested_language, []),
                    "tex_source_unavailable_no_ocr",
                    render_dpi,
                    True,
                    progress_callback=progress_callback,
                    is_batch=is_batch,
                    stored_input_path=stored_path,
                )

        _emit_progress(progress_callback, 2, "Подготовка документа", original_name)
        stage_started_at = time.perf_counter()
        pages, layer_blocks = render_document(
            stored_path,
            document_id,
            render_dpi,
            max_pages,
            progress_callback=_page_progress(progress_callback, 3, 18, "Рендер страниц"),
        )
        _emit_progress(progress_callback, 19, "Нормализация текстового слоя", f"{len(layer_blocks)} blocks")
        stage_times["pages_render_time"] = time.perf_counter() - stage_started_at
        stage_started_at = time.perf_counter()
        normalized_layer_blocks = normalize_text_blocks(layer_blocks)
        stage_times["text_layer_time"] = time.perf_counter() - stage_started_at
        requested_language = ocr_lang or settings.ocr_lang
        language, language_reason = _resolve_ocr_language_with_reason(requested_language, normalized_layer_blocks)
        tex_id = normalize_arxiv_id(arxiv_id) or normalize_arxiv_id(original_name)
        if ocr_mode == "tex_source":
            _emit_progress(progress_callback, 22, "Загрузка TeX-источника", tex_id or "no arXiv id")
            text_blocks: list[TextBlock] = []
            text_with_tokens: list[TextBlock] = []
            formulas: list[FormulaBlock] = []
            formula_regions: list[FormulaRegion] = []
            if not tex_id:
                warnings.append("Режим TeX-источника требует arXiv ID или имя файла, похожее на arXiv ID.")
            elif stored_path.suffix.lower() != ".pdf":
                warnings.append("Режим TeX-источника сейчас ожидает PDF и исходники arXiv.")
            else:
                source_dir, source_warnings = fetch_arxiv_source(tex_id, document_id)
                warnings.extend(source_warnings)
                if source_dir is not None:
                    _emit_progress(progress_callback, 46, "Разбор TeX-источника", str(source_dir))
                    tex_document = parse_tex_document(source_dir)
                    warnings.extend(tex_document.warnings)
                    text_blocks = normalize_text_blocks(tex_document.text_blocks)
                    text_with_tokens = normalize_text_blocks(tex_document.text_with_tokens)
                    formulas = normalize_formula_blocks(tex_document.formulas)

            _emit_progress(progress_callback, 75, "Извлечение сущностей и связей", None)
            entities, relations = extract_entities(text_blocks, formulas)
            relations.extend(bind_formulas_to_context(formulas, text_with_tokens))
            graph = build_graph(text_with_tokens, formulas, entities, relations)
            metagraph = build_metagraph(document_id, text_blocks, formulas, entities, relations)
            result = ProcessingResult(
                document_id=document_id,
                filename=original_name,
                created_at=datetime.utcnow(),
                status="partial" if warnings else "ok",
                warnings=warnings,
                pages=pages,
                text_blocks=text_blocks,
                text_with_tokens=text_with_tokens,
                formula_regions=formula_regions,
                formulas=formulas,
                entities=entities,
                relations=relations,
                graph=graph,
                metagraph=metagraph,
            )
            return _save_result_bundle(
                result,
                ocr_mode,
                device_mode,
                requested_language,
                language,
                language_reason,
                render_dpi,
                prefer_tex_source,
                progress_callback=progress_callback,
                is_batch=is_batch,
                stored_input_path=stored_path,
            )
        if ocr_mode == "marker":
            _emit_progress(progress_callback, 24, "Разбор документа через Marker", None)
            text_blocks, formulas, marker_warnings = MarkerAdapter(device=device_mode).parse_document(stored_path, max_pages)
            warnings.extend(marker_warnings)
            _emit_progress(progress_callback, 58, "Нормализация формул и токенов", None)
            text_blocks = normalize_text_blocks(text_blocks)
            formulas = normalize_formula_blocks(formulas)
            formulas = rescue_formula_definitions(formulas, normalized_layer_blocks)
            formulas = reconcile_formula_candidates_with_text_layer(formulas, normalized_layer_blocks)
            formula_regions = build_formula_regions(formulas)
            formulas = assign_formula_tokens(formulas, formula_regions)
            text_with_tokens = reconstruct_text_with_formula_tokens(text_blocks, formula_regions)
            _emit_progress(progress_callback, 74, "Извлечение сущностей и графа", None)
            entities, relations = extract_entities(text_blocks, formulas)
            relations.extend(bind_formulas_to_context(formulas, text_with_tokens))
            graph = build_graph(text_with_tokens, formulas, entities, relations)
            metagraph = build_metagraph(document_id, text_blocks, formulas, entities, relations)

            result = ProcessingResult(
                document_id=document_id,
                filename=original_name,
                created_at=datetime.utcnow(),
                status="partial" if warnings else "ok",
                warnings=warnings,
                pages=pages,
                text_blocks=text_blocks,
                text_with_tokens=text_with_tokens,
                formula_regions=formula_regions,
                formulas=formulas,
                entities=entities,
                relations=relations,
                graph=graph,
                metagraph=metagraph,
            )
            return _save_result_bundle(
                result,
                ocr_mode,
                device_mode,
                requested_language,
                language,
                language_reason,
                render_dpi,
                prefer_tex_source,
                progress_callback=progress_callback,
                is_batch=is_batch,
                stored_input_path=stored_path,
            )
        needs_text_ocr = _needs_text_ocr(ocr_mode, layer_blocks, normalized_layer_blocks, language)
        has_good_layer_text = bool(layer_blocks) and sum(len(block.text or "") for block in normalized_layer_blocks) > 500 and not _looks_corrupted(normalized_layer_blocks)
        needs_structure = (
            settings.enable_paddle
            and ocr_mode not in {"text_layer", "tex_source", "marker", "tesseract", "standard"}
        ) or ocr_mode in {"structure", "hybrid_tesseract"} or (ocr_mode == "hybrid" and language == "ru") or needs_text_ocr
        if ocr_mode == "standard" and has_good_layer_text:
            needs_structure = False
            warnings.append("Стандартный режим использовал текстовый слой PDF и пропустил OCR текста/разметки PPStructureV3.")
        structure_pages = _prepare_structure_pages(pages, structure_max_dpi, warnings) if needs_structure else pages
        text_blocks = normalized_layer_blocks
        text_with_tokens = normalized_layer_blocks
        tex_formulas = []
        if prefer_tex_source and tex_id and stored_path.suffix.lower() == ".pdf":
            source_dir, source_warnings = fetch_arxiv_source(tex_id, document_id)
            warnings.extend(source_warnings)
            if source_dir is not None:
                tex_formulas, tex_warnings = extract_tex_formulas(source_dir)
                warnings.extend(tex_warnings)
                if not tex_formulas:
                    warnings.append(f"В исходниках arXiv {tex_id} не найдено извлекаемых TeX-формул; используются формулы из OCR.")

        formula_regions: list[FormulaRegion] = []
        masking_regions: list[FormulaRegion] = []
        detected_formulas: list[FormulaBlock] = []

        if needs_text_ocr:
            _emit_progress(progress_callback, 24, "Поиск формульных кандидатов", None)
            detected_formulas, masking_regions = _detect_formula_candidates(
                normalized_layer_blocks,
                structure_pages,
                device_mode,
                warnings,
                progress_callback=progress_callback,
            )
            masked_pages = mask_formula_regions(
                pages,
                masking_regions,
                settings.processed_dir / document_id / "masked",
            )
            _emit_progress(progress_callback, 34, "OCR текста по страницам", None)
            text_blocks, ocr_warnings = _recognize_text_from_pages(
                masked_pages,
                ocr_mode,
                device_mode,
                language,
                progress_callback=_page_progress(progress_callback, 34, 56, "OCR текста"),
            )
            warnings.extend(ocr_warnings)
            text_blocks = normalize_text_blocks(text_blocks)
        elif ocr_mode == "structure":
            _emit_progress(progress_callback, 26, "Анализ структуры страниц", None)
            text_blocks, detected_formulas, structure_warnings = _call_with_optional_progress(
                PaddleStructureAdapter(device=device_mode).parse_pages,
                structure_pages,
                progress_callback=_page_progress(progress_callback, 26, 56, "Структурный анализ"),
            )
            warnings.extend(structure_warnings)
            if not text_blocks and normalized_layer_blocks:
                warnings.append("PPStructureV3 не извлек текст; используется текстовый слой PDF.")
                text_blocks = normalized_layer_blocks
            else:
                text_blocks = normalize_text_blocks(text_blocks)
        else:
            _emit_progress(progress_callback, 24, "Сбор текста и формул", None)
            text_blocks, structure_formulas = _choose_blocks_and_formulas(
                pages,
                structure_pages,
                layer_blocks,
                ocr_mode,
                device_mode,
                language,
                warnings,
                progress_callback=progress_callback,
            )
            text_blocks = normalize_text_blocks(text_blocks)
            detected_formulas = merge_formula_candidates(extract_formulas(text_blocks), structure_formulas)

        if tex_formulas:
            formulas = tex_formulas
        else:
            formulas = detected_formulas
            needs_formula_ocr = any(
                formula.source != "tex_source"
                and formula.bbox is not None
                and (formula.confidence or 0.0) < 0.86
                for formula in formulas
            )
            is_russian_document = (
                language == "ru"
                or requested_language == "ru"
                or _has_cyrillic_text(original_name)
                or _has_cyrillic_blocks(normalized_layer_blocks or text_blocks)
            )
            if False and is_russian_document and needs_formula_ocr:
                needs_formula_ocr = False
                warnings.append(
                    "Нейросетевое уточнение формул пропущено в стандартном режиме, "
                    "чтобы обработка оставалась быстрой и не зависала на ложных формульных областях."
                )
            elif False and is_russian_document and needs_formula_ocr:
                needs_formula_ocr = False
                warnings.append(
                    "Нейросетевое уточнение формул пропущено для русскоязычного PDF, "
                    "чтобы не блокировать обработку на ложных формульных областях."
                )
            if formulas and needs_formula_ocr and settings.enable_formula_ocr:
                _emit_progress(progress_callback, 58, "Распознавание формул", f"{len(formulas)} кандидатов")
                stage_started_at = time.perf_counter()
                formulas, formula_warnings = _call_with_optional_progress(
                    FormulaRecognitionAdapter(device=device_mode).refine,
                    pages,
                    formulas,
                    normalized_layer_blocks or text_blocks,
                    progress_callback=_page_progress(progress_callback, 58, 74, "Уточнение формул"),
                )
                stage_times["formula_recognition_time"] = time.perf_counter() - stage_started_at
                warnings.extend(formula_warnings)
            _emit_progress(progress_callback, 76, "Нормализация формул и токенов", None)
            formulas = normalize_formula_blocks(formulas)
            formulas = rescue_formula_definitions(formulas, normalized_layer_blocks)
            formulas = reconcile_formula_candidates_with_text_layer(formulas, normalized_layer_blocks)
        pre_regions = build_formula_regions(formulas)
        formulas = assign_formula_tokens(formulas, pre_regions)
        formulas = consolidate_assigned_formulas(formulas)
        formulas = reindex_formulas(formulas)
        formulas = [
            formula.model_copy(update={"token": None, "formula_region_id": None})
            for formula in formulas
        ]
        formula_regions = build_formula_regions(formulas)
        formulas = assign_formula_tokens(formulas, formula_regions)
        text_with_tokens = reconstruct_text_with_formula_tokens(text_blocks, formula_regions)
        _emit_progress(progress_callback, 82, "Семантика и связи", None)
        entities, relations = extract_entities(text_blocks, formulas)
        relations.extend(bind_formulas_to_context(formulas, text_with_tokens))
        _emit_progress(progress_callback, 88, "Построение графа и метаграфа", None)
        stage_started_at = time.perf_counter()
        graph = build_graph(text_with_tokens, formulas, entities, relations)
        metagraph = build_metagraph(document_id, text_blocks, formulas, entities, relations)
        stage_times["graph_build_time"] = time.perf_counter() - stage_started_at

        result = ProcessingResult(
            document_id=document_id,
            filename=original_name,
            created_at=datetime.utcnow(),
            status="partial" if warnings else "ok",
            warnings=warnings,
            pages=pages,
            text_blocks=text_blocks,
            text_with_tokens=text_with_tokens,
            formula_regions=formula_regions,
            formulas=formulas,
            entities=entities,
            relations=relations,
            graph=graph,
            metagraph=metagraph,
            timing=_build_timing(stage_times, total_started_at),
        )
    except Exception as exc:
        result = ProcessingResult(
            document_id=document_id,
            filename=original_name,
            created_at=datetime.utcnow(),
            status="error",
            warnings=[str(exc)],
        )

    requested_language = locals().get("requested_language") or ocr_lang or settings.ocr_lang
    profile_language = locals().get("language") or _resolve_ocr_language(requested_language, [])
    language_reason = locals().get("language_reason") or "fallback_default_en"
    return _save_result_bundle(
        result,
        ocr_mode,
        device_mode,
        requested_language,
        profile_language,
        language_reason,
        render_dpi,
        prefer_tex_source,
        progress_callback=progress_callback,
        is_batch=is_batch,
        stored_input_path=stored_path,
    )


def _save_result_bundle(
    result: ProcessingResult,
    ocr_mode: str,
    device_mode: str,
    requested_ocr_lang: str,
    resolved_ocr_lang: str,
    ocr_language_detection_reason: str,
    render_dpi: int | None,
    prefer_tex_source: bool,
    progress_callback: Callable[[float, str, str | None], None] | None = None,
    is_batch: bool = False,
    stored_input_path: Path | None = None,
) -> ProcessingResult:
    export_started_at = time.perf_counter()
    result.timing = _ensure_timing(result.timing)
    _attach_formula_interpretations(result)
    result.processing_steps = _build_processing_steps(result, ocr_mode)
    llm_step = manual_refinement_step(result)
    if llm_step and not any(step.get("stage") == "llm_refinement" for step in result.processing_steps):
        result.processing_steps.append(llm_step)
    _emit_progress(progress_callback, 92, "Подготовка данных для графа и расширенного метаграфа", None)
    _emit_progress(progress_callback, 93, "Подготовка структурированного экспорта", None)
    result_path = settings.results_dir / f"{result.document_id}.json"
    result.result_path = str(result_path)
    structured = build_structured_document(
        result,
        ocr_mode=ocr_mode,
        device=device_mode,
        ocr_lang=resolved_ocr_lang,
        requested_device=device_mode,
        requested_ocr_lang=requested_ocr_lang,
        resolved_ocr_lang=resolved_ocr_lang,
        ocr_language_detection_reason=ocr_language_detection_reason,
        render_dpi=render_dpi,
        prefer_tex_source=prefer_tex_source,
    )
    _emit_progress(progress_callback, 94, "Сборка JSON для метаграфа", None)
    graph_ready = build_graph_ready_document(result, structured)
    _emit_progress(progress_callback, 96, "Сборка модели метаграфа", None)
    rich_metagraph = build_metagraph_from_graph_ready(graph_ready)
    result.metagraph = metagraph_to_knowledge_graph(rich_metagraph)
    graph_input, semantic_metagraph, _variable_index = save_semantic_artifacts(graph_ready, settings.results_dir)
    metagraph_validation = validate_metagraph(semantic_metagraph)
    result.metagraph_validation = metagraph_validation
    graph_demo_dir = settings.processed_dir / result.document_id / "graph"
    graph_demo_dir.mkdir(parents=True, exist_ok=True)
    (graph_demo_dir / "graph_input.json").write_text(
        json.dumps({"nodes": graph_input["nodes"], "edges": graph_input["edges"]}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (graph_demo_dir / "metagraph.json").write_text(json.dumps(semantic_metagraph, ensure_ascii=False, indent=2), encoding="utf-8")
    (graph_demo_dir / "variable_index.json").write_text(json.dumps(_variable_index, ensure_ascii=False, indent=2), encoding="utf-8")
    (graph_demo_dir / "metagraph_validation.json").write_text(json.dumps(metagraph_validation, ensure_ascii=False, indent=2), encoding="utf-8")
    (graph_demo_dir / "formulas.json").write_text(json.dumps(_formula_export_rows(graph_ready), ensure_ascii=False, indent=2), encoding="utf-8")
    (graph_demo_dir / "formula_interpretations.json").write_text(
        json.dumps(_formula_interpretations(graph_ready), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    create_demo_summary(
        {
            "pages": len(result.pages) or 1,
            "formulas": len(graph_ready.formulas),
            "variables": len(_variable_index),
            "meta_nodes": len(semantic_metagraph.get("meta_nodes", [])),
            "meta_edges": len(semantic_metagraph.get("meta_edges", [])),
            "main_links": semantic_metagraph.get("meta_edges", []),
            "generated_files": [
                "graph_input.json",
                "metagraph.json",
                "metagraph_validation.json",
                "variable_index.json",
                "formulas.json",
                "formula_interpretations.json",
                "graph_view.html",
                "formula_graph_view.html",
                "metagraph_view.html",
                "demo_dashboard.html",
            ],
        },
        None,
        graph_demo_dir,
    )
    _emit_progress(progress_callback, 95, "Сохранение структурированного JSON и данных для графа", None)
    _emit_progress(progress_callback, 98, "Сохранение JSON-экспортов", None)
    save_structured_document(structured, settings.results_dir / f"{result.document_id}.structured.json")
    save_graph_ready_document(graph_ready, settings.results_dir / f"{result.document_id}.graph_ready.json")
    (settings.results_dir / f"{result.document_id}.metagraph_validation.json").write_text(
        json.dumps(metagraph_validation, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (settings.results_dir / f"{result.document_id}.formulas.json").write_text(
        json.dumps(_formula_export_rows(graph_ready), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (settings.results_dir / f"{result.document_id}.formula_interpretations.json").write_text(
        json.dumps(_formula_interpretations(graph_ready), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    save_metagraph(rich_metagraph, settings.results_dir / f"{result.document_id}.rich_metagraph.json")
    metrics = compute_metagraph_metrics(rich_metagraph.to_dict(), json.loads(result.model_dump_json()))
    (settings.results_dir / f"{result.document_id}.metagraph_metrics.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    result.timing["export_time"] = round(time.perf_counter() - export_started_at, 4)
    result.timing["per_stage_time_sec"]["export_time"] = result.timing["export_time"]
    result.timing["total_time_sec"] = round(float(result.timing.get("total_time_sec") or 0.0) + result.timing["export_time"], 4)
    result.save_json(result_path)
    _emit_progress(progress_callback, 99, "Сохранение данных визуализации", None)
    visualization = export_visualization_payload(graph_ready, mode="overview")
    (settings.results_dir / f"{result.document_id}.visualization.json").write_text(
        json.dumps(visualization, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    try:
        generate_graph_view(
            {"nodes": graph_input["nodes"], "edges": graph_input["edges"]},
            graph_demo_dir / "graph_view.html",
        )
        generate_formula_graph_view({"nodes": graph_input["nodes"], "edges": graph_input["edges"]}, graph_demo_dir / "formula_graph_view.html")
        generate_metagraph_view(semantic_metagraph, graph_demo_dir / "metagraph_view.html")
        generate_demo_dashboard(
            {
                "document_id": result.document_id,
                "formulas": len(graph_ready.formulas),
                "variables": len(_variable_index),
                "meta_nodes": len(semantic_metagraph.get("meta_nodes", [])),
                "meta_edges": len(semantic_metagraph.get("meta_edges", [])),
                "generated_files": [
                    "graph_view.html",
                    "formula_graph_view.html",
                    "metagraph_view.html",
                    "demo_summary.md",
                ],
            },
            graph_demo_dir,
        )
        generate_graph_view(
            {"nodes": graph_input["nodes"], "edges": graph_input["edges"]},
            settings.results_dir / f"{result.document_id}.graph_view.html",
        )
        generate_formula_graph_view({"nodes": graph_input["nodes"], "edges": graph_input["edges"]}, settings.results_dir / f"{result.document_id}.formula_graph_view.html")
        generate_metagraph_view(semantic_metagraph, settings.results_dir / f"{result.document_id}.metagraph_view.html")
    except Exception as exc:
        result.warnings.append(f"HTML-визуализация не была создана: {exc}")
    cleanup_counts = cleanup_after_processing(result.document_id, stored_input_path)
    if any(cleanup_counts.values()):
        result.timing["storage_cleanup"] = cleanup_counts
        result.save_json(result_path)
    _emit_progress(progress_callback, 100, "Готово", result.document_id)
    return result


def _formula_export_rows(graph_ready) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    contexts_by_formula = {context.formula_id: context for context in graph_ready.formula_contexts}
    for formula in graph_ready.formulas:
        interpretation = interpret_formula_record(formula, contexts_by_formula.get(formula.id))
        rows.append(
            {
                "formula_id": formula.token.strip("[]") if formula.token else formula.id,
                "id": formula.id,
                "token": formula.token,
                "raw_latex": formula.raw_latex or formula.latex,
                "cleaned_latex": formula.cleaned_latex or formula.latex,
                "normalized_latex": formula.normalized_latex or formula.latex,
                "plain_formula_text": formula.plain_formula_text or interpretation.get("plain_text", ""),
                "formula_interpretation": interpretation,
                "interpretation": interpretation.get("summary", ""),
                "latex": formula.latex,
                "formula_type": formula.kind,
                "formula_metavertex": {
                    "id": formula.meta_semantics.metavertex_id or f"{formula.id}_mv",
                    "semantic_type": formula.meta_semantics.semantic_type,
                    "outer_document_object": formula.meta_semantics.outer_document_object,
                    "inner_expression_object": formula.meta_semantics.inner_expression_object,
                    "internal_roles": list(formula.meta_semantics.internal_roles),
                    "context_ids": list(formula.meta_semantics.context_ids),
                    "paragraph_ids": list(formula.meta_semantics.paragraph_ids),
                    "variable_ids": list(formula.meta_semantics.variable_ids),
                },
                "semantic_metaedges": [item.model_dump() for item in formula.meta_semantics.metaedges],
                "variables": formula.symbols,
                "recognition_engine": formula.source,
                "recognition_confidence": formula.confidence,
                "warnings": formula.quality_flags,
            }
        )
    return rows


def _formula_interpretations(graph_ready) -> list[dict[str, object]]:
    contexts_by_formula = {context.formula_id: context for context in graph_ready.formula_contexts}
    return [
        {
            "formula_id": formula.token.strip("[]") if formula.token else formula.id,
            "id": formula.id,
            "token": formula.token,
            "interpretation": interpret_formula_record(formula, contexts_by_formula.get(formula.id)),
            "formula_metavertex": {
                "id": formula.meta_semantics.metavertex_id or f"{formula.id}_mv",
                "semantic_type": formula.meta_semantics.semantic_type,
                "outer_document_object": formula.meta_semantics.outer_document_object,
                "inner_expression_object": formula.meta_semantics.inner_expression_object,
                "internal_roles": list(formula.meta_semantics.internal_roles),
            },
            "semantic_metaedges": [item.model_dump() for item in formula.meta_semantics.metaedges],
        }
        for formula in graph_ready.formulas
    ]


def _attach_formula_interpretations(result: ProcessingResult) -> None:
    context_blocks = result.text_with_tokens or result.text_blocks
    for formula in result.formulas:
        context = _formula_context_window(formula, context_blocks)
        variables = _infer_formula_symbols(formula.latex)
        interpretation = interpret_formula(
            formula.normalized_latex or formula.cleaned_latex or formula.latex,
            variables=variables,
            context=context,
        )
        formula.formula_interpretation = interpretation
        formula.interpretation = str(interpretation.get("summary") or "")
        if not formula.plain_formula_text:
            formula.plain_formula_text = str(interpretation.get("plain_text") or "")


def _formula_context_window(formula: FormulaBlock, blocks: list[TextBlock], radius: int = 260) -> str:
    token = formula.token or ""
    preferred: list[str] = []
    fallback: list[str] = []
    for block in blocks:
        text = str(block.text or "")
        if not text:
            continue
        if formula.context_block_id and block.id == formula.context_block_id:
            preferred.append(text)
        elif token and token in text:
            index = text.find(token)
            start = max(0, index - radius)
            end = min(len(text), index + len(token) + radius)
            preferred.append(text[start:end])
        elif block.page_number == formula.page_number:
            fallback.append(text)
    value = " ".join(preferred or fallback[:2])
    return " ".join(value.split())[:900]


def _infer_formula_symbols(latex: str) -> list[str]:
    ignored = {
        "\\frac",
        "\\sum",
        "\\prod",
        "\\int",
        "\\iint",
        "\\iiint",
        "\\oint",
        "\\lim",
        "\\min",
        "\\max",
        "\\argmin",
        "\\argmax",
        "\\left",
        "\\right",
        "\\begin",
        "\\end",
        "\\sin",
        "\\cos",
        "\\tan",
        "\\log",
        "\\ln",
        "\\exp",
        "\\sqrt",
        "\\cdot",
        "\\times",
        "\\div",
        "\\le",
        "\\leq",
        "\\ge",
        "\\geq",
        "\\ne",
        "\\neq",
        "\\approx",
        "\\sim",
        "\\equiv",
        "\\in",
        "\\notin",
        "\\subset",
        "\\subseteq",
        "\\supset",
        "\\supseteq",
        "\\cup",
        "\\cap",
        "\\setminus",
        "\\forall",
        "\\exists",
        "\\land",
        "\\lor",
        "\\neg",
        "\\to",
        "\\mapsto",
        "\\rightarrow",
        "\\leftarrow",
        "\\Rightarrow",
        "\\Leftrightarrow",
        "\\partial",
        "\\nabla",
        "\\infty",
        "\\mathrm",
        "\\mathit",
        "\\mathbf",
        "\\text",
    }
    symbols: list[str] = []
    for match in re.finditer(r"\\[A-Za-z]+|[A-Za-z][A-Za-z0-9_]*", latex or ""):
        token = match.group(0)
        if token in ignored:
            continue
        normalized = token.lstrip("\\")
        if normalized and normalized not in symbols:
            symbols.append(normalized)
    return symbols[:32]


def _try_process_tex_source(
    document_id: str,
    stored_path: Path,
    original_name: str,
    tex_id: str | None,
    warnings: list[str],
    progress_callback: Callable[[float, str, str | None], None] | None = None,
) -> ProcessingResult | None:
    if not tex_id:
        warnings.append("Режим TeX-источника требует arXiv ID или имя файла, похожее на arXiv ID.")
        return None
    if stored_path.suffix.lower() != ".pdf":
        warnings.append("Режим TeX-источника сейчас ожидает PDF и исходники arXiv.")
        return None

    _emit_progress(progress_callback, 8, "Загрузка TeX-источника", tex_id)
    source_dir, source_warnings = fetch_arxiv_source(tex_id, document_id)
    warnings.extend(source_warnings)
    if source_dir is None:
        return None

    _emit_progress(progress_callback, 35, "Разбор TeX-источника", str(source_dir))
    tex_document = parse_tex_document(source_dir)
    warnings.extend(tex_document.warnings)
    text_blocks = normalize_text_blocks(tex_document.text_blocks)
    text_with_tokens = normalize_text_blocks(tex_document.text_with_tokens)
    formulas = normalize_formula_blocks(tex_document.formulas)

    _emit_progress(progress_callback, 75, "Построение смысловых связей", None)
    entities, relations = extract_entities(text_blocks, formulas)
    relations.extend(bind_formulas_to_context(formulas, text_with_tokens))
    graph = build_graph(text_with_tokens, formulas, entities, relations)
    metagraph = build_metagraph(document_id, text_blocks, formulas, entities, relations)

    return ProcessingResult(
        document_id=document_id,
        filename=original_name,
        created_at=datetime.utcnow(),
        status="partial" if warnings else "ok",
        warnings=warnings,
        pages=[],
        text_blocks=text_blocks,
        text_with_tokens=text_with_tokens,
        formula_regions=[],
        formulas=formulas,
        entities=entities,
        relations=relations,
        graph=graph,
        metagraph=metagraph,
    )


def _resolve_ocr_language(requested: str | None, layer_blocks: list[TextBlock]) -> str:
    return _resolve_ocr_language_with_reason(requested, layer_blocks)[0]


def _resolve_ocr_language_with_reason(requested: str | None, layer_blocks: list[TextBlock]) -> tuple[str, str]:
    requested = (requested or "auto").lower().strip()
    if requested in {"en", "ru"}:
        return requested, "requested_explicitly"
    detected = detect_ocr_language(layer_blocks)
    if detected:
        return detected, "auto_detected_from_text_layer"
    return "en", "fallback_default_en"


def detect_ocr_language(blocks: list[TextBlock]) -> str | None:
    text = "\n".join(block.text for block in blocks[:120] if block.text).strip()
    if len(text) < 80:
        return None
    cyrillic = sum(1 for char in text if "А" <= char <= "я" or char in "Ёё")
    latin = sum(1 for char in text if "A" <= char <= "Z" or "a" <= char <= "z")
    letters = cyrillic + latin
    if letters < 40:
        return None
    return "ru" if cyrillic / letters >= 0.25 else "en"


def _has_cyrillic_blocks(blocks: list[TextBlock]) -> bool:
    text = "\n".join(block.text for block in blocks[:80] if block.text)
    return _has_cyrillic_text(text)


def _has_cyrillic_text(text: str | None) -> bool:
    value = str(text or "")
    letters = [char for char in value if char.isalpha()]
    if not letters:
        return False
    cyrillic = sum(1 for char in letters if "А" <= char <= "я" or char in "Ёё")
    return cyrillic >= 8 or cyrillic / max(1, len(letters)) >= 0.18


def _detect_formula_candidates(
    layer_blocks: list[TextBlock],
    structure_pages: list[PageImage],
    device_mode: str,
    warnings: list[str],
    progress_callback: Callable[[float, str, str | None], None] | None = None,
) -> tuple[list[FormulaBlock], list[FormulaRegion]]:
    layer_formulas = extract_formulas(layer_blocks) if layer_blocks else []
    structure_formulas: list[FormulaBlock] = []
    if settings.enable_paddle:
        _, structure_formulas, structure_warnings = _call_with_optional_progress(
            PaddleStructureAdapter(device=device_mode).parse_pages,
            structure_pages,
            progress_callback=_page_progress(progress_callback, 24, 32, "Поиск формул на страницах"),
        )
        warnings.extend(structure_warnings)
    formulas = merge_formula_candidates(layer_formulas, structure_formulas)
    regions = build_formula_regions(formulas)
    return formulas, regions


def _recognize_text_from_pages(
    pages: list[PageImage],
    ocr_mode: str,
    device_mode: str,
    ocr_lang: str,
    progress_callback: Callable[[float, str, str | None], None] | None = None,
) -> tuple[list[TextBlock], list[str]]:
    primary_adapter = _primary_text_ocr_adapter(ocr_mode, device_mode, ocr_lang)
    return _call_with_optional_progress(primary_adapter.recognize_pages, pages, progress_callback=progress_callback)


def _needs_text_ocr(
    ocr_mode: str,
    layer_blocks: list[TextBlock],
    normalized_layer_blocks: list[TextBlock],
    ocr_lang: str,
) -> bool:
    if ocr_mode == "text_layer":
        return False
    if ocr_mode == "structure":
        return False
    if ocr_mode in {"hybrid_tesseract", "tesseract"}:
        return True
    if ocr_mode == "hybrid":
        if layer_blocks and not _looks_corrupted(normalized_layer_blocks):
            return False
        return ocr_lang == "ru" or settings.enable_paddle
    if ocr_mode == "auto":
        has_enough_layer_text = sum(len(block.text) for block in layer_blocks) > 500
        return not has_enough_layer_text and settings.enable_paddle
    if ocr_mode == "standard":
        has_enough_layer_text = sum(len(block.text) for block in normalized_layer_blocks) > 500
        return (not has_enough_layer_text or _looks_corrupted(normalized_layer_blocks)) and settings.enable_paddle
    return False


def _choose_blocks_and_formulas(
    pages,
    structure_pages,
    layer_blocks: list[TextBlock],
    ocr_mode: str,
    device_mode: str,
    ocr_lang: str,
    warnings: list[str],
    progress_callback: Callable[[float, str, str | None], None] | None = None,
):
    repaired_layer_blocks = normalize_text_blocks(layer_blocks) if layer_blocks else []
    if ocr_mode == "text_layer":
        if not layer_blocks:
            warnings.append("Текстовый слой PDF не найден; результат не содержит OCR-текста.")
        return layer_blocks, []

    if ocr_mode == "structure":
        text_blocks, formulas, structure_warnings = _call_with_optional_progress(
            PaddleStructureAdapter(device=device_mode).parse_pages,
            structure_pages,
            progress_callback=_page_progress(progress_callback, 26, 56, "Структурный анализ"),
        )
        warnings.extend(structure_warnings)
        if text_blocks:
            return text_blocks, formulas
        if layer_blocks:
            warnings.append("PPStructureV3 не извлек текст; используется текстовый слой PDF.")
            return layer_blocks, formulas
        return [], formulas

    if ocr_mode == "hybrid":
        formulas = _visual_formula_candidates(structure_pages, device_mode, warnings, progress_callback=progress_callback)
        if layer_blocks and not _looks_corrupted(repaired_layer_blocks):
            return layer_blocks, formulas
        if layer_blocks:
            warnings.append("Текстовый слой PDF выглядит поврежденным; вместо встроенного текста используется OCR.")
        text_blocks, ocr_warnings = _recognize_text_from_pages(
            pages,
            ocr_mode,
            device_mode,
            ocr_lang,
            progress_callback=_page_progress(progress_callback, 34, 56, "OCR текста"),
        )
        warnings.extend(ocr_warnings)
        return text_blocks, formulas

    if ocr_mode == "hybrid_tesseract":
        _, formulas, structure_warnings = _call_with_optional_progress(
            PaddleStructureAdapter(device=device_mode).parse_pages,
            structure_pages,
            progress_callback=_page_progress(progress_callback, 24, 40, "Структурный анализ"),
        )
        warnings.extend(structure_warnings)
        text_blocks, ocr_warnings = _recognize_text_from_pages(
            pages,
            ocr_mode,
            device_mode,
            ocr_lang,
            progress_callback=_page_progress(progress_callback, 40, 56, "OCR текста"),
        )
        warnings.extend(ocr_warnings)
        return text_blocks, formulas

    if ocr_mode == "tesseract":
        text_blocks, ocr_warnings = _recognize_text_from_pages(
            pages,
            ocr_mode,
            device_mode,
            ocr_lang,
            progress_callback=_page_progress(progress_callback, 34, 56, "OCR текста"),
        )
        warnings.extend(ocr_warnings)
        return text_blocks, []

    has_enough_layer_text = sum(len(block.text) for block in layer_blocks) > 500
    if ocr_mode == "standard" and has_enough_layer_text and any("PPStructureV3" in warning for warning in warnings):
        warnings.append("Стандартный режим использует облегченное извлечение формул из текстового слоя.")
        return layer_blocks, []

    if ocr_mode in {"auto", "standard"} and has_enough_layer_text:
        formulas = _visual_formula_candidates(structure_pages, device_mode, warnings, progress_callback=progress_callback)
        return layer_blocks, formulas

    if not settings.enable_paddle:
        warnings.append("PaddleOCR отключен; используется только текстовый слой PDF.")
        return layer_blocks, []

    ocr_blocks, ocr_warnings = _recognize_text_from_pages(
        pages,
        ocr_mode,
        device_mode,
        ocr_lang,
        progress_callback=_page_progress(progress_callback, 34, 56, "OCR текста"),
    )
    warnings.extend(ocr_warnings)
    if ocr_blocks:
        return ocr_blocks, []
    if layer_blocks:
        warnings.append("OCR не извлек текст; используется текстовый слой PDF.")
    return layer_blocks, []


def _visual_formula_candidates(
    structure_pages: list[PageImage],
    device_mode: str,
    warnings: list[str],
    progress_callback: Callable[[float, str, str | None], None] | None = None,
) -> list[FormulaBlock]:
    if not settings.enable_paddle:
        return []
    _, formulas, structure_warnings = _call_with_optional_progress(
        PaddleStructureAdapter(device=device_mode).parse_pages,
        structure_pages,
        progress_callback=_page_progress(progress_callback, 24, 40, "Поиск формул на страницах"),
    )
    warnings.extend(structure_warnings)
    return formulas


def _prepare_structure_pages(pages: list[PageImage], max_dpi: int, warnings: list[str]) -> list[PageImage]:
    if not pages or all(page.dpi <= max_dpi for page in pages):
        return pages
    warnings.append(
        f"Для PPStructureV3 используются уменьшенные копии страниц с {max_dpi} DPI, чтобы снизить расход памяти GPU; OCR текста сохраняет исходный DPI."
    )
    result: list[PageImage] = []
    for page in pages:
        if page.dpi <= max_dpi:
            result.append(page)
            continue
        source = Path(page.image_path)
        target = source.with_name(f"{source.stem}_structure_{max_dpi}dpi{source.suffix}")
        scale = max_dpi / page.dpi
        with Image.open(source) as image:
            width = max(1, int(image.width * scale))
            height = max(1, int(image.height * scale))
            resized = image.resize((width, height), Image.Resampling.LANCZOS)
            resized.save(target)
        result.append(
            page.model_copy(
                update={
                    "image_path": str(target),
                    "width": width,
                    "height": height,
                    "dpi": max_dpi,
                }
            )
        )
    return result


def _looks_corrupted(blocks: list[TextBlock]) -> bool:
    text = "\n".join(block.text for block in blocks[:80])
    if not text:
        return False
    suspicious = sum(text.count(ch) for ch in "¶�")
    mojibake = sum(text.count(marker) for marker in ("Ã", "Â", "â€", "Ð", "Ñ"))
    cyrillic = sum(1 for ch in text if "А" <= ch <= "я" or ch == "ё" or ch == "Ё")
    latin = sum(1 for ch in text if "A" <= ch <= "z")
    total_letters = cyrillic + latin
    return suspicious >= 3 or mojibake >= 8 or (total_letters > 100 and cyrillic < total_letters * 0.15 and mojibake >= 3)


def _primary_text_ocr_adapter(ocr_mode: str, device_mode: str, ocr_lang: str):
    backend = (settings.text_ocr_backend or "paddle").lower().strip()
    if backend == "got_ocr":
        backend = "paddle"
    if ocr_mode in {"hybrid_tesseract", "tesseract"}:
        return TesseractOCRAdapter(lang=ocr_lang)
    if ocr_lang == "ru":
        return TesseractOCRAdapter(lang=ocr_lang)
    return PaddleOCRAdapter(device=device_mode, lang=ocr_lang)


def _emit_progress(
    progress_callback: Callable[[float, str, str | None], None] | None,
    percent: float,
    stage: str,
    detail: str | None,
) -> None:
    if progress_callback is None:
        return
    progress_callback(max(0.0, min(100.0, percent)), stage, _translate_progress_detail(detail))


def _translate_progress_detail(detail: str | None) -> str | None:
    if detail is None:
        return None
    text = str(detail)
    replacements = {
        " candidates": " кандидатов",
        " candidate": " кандидат",
        " blocks": " блоков",
        " block": " блок",
        "no arXiv id": "arXiv ID не указан",
        "graph-ready": "данные для графа",
        "rich metagraph": "расширенный метаграф",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    return text


def _page_progress(
    progress_callback: Callable[[float, str, str | None], None] | None,
    start_percent: float,
    end_percent: float,
    stage: str,
):
    def callback(index: int, total: int, detail: str | None = None) -> None:
        ratio = 1.0 if total <= 0 else index / total
        percent = start_percent + (end_percent - start_percent) * ratio
        suffix = f"{index}/{total}"
        if detail:
            suffix = f"{suffix} | {detail}"
        _emit_progress(progress_callback, percent, stage, suffix)

    return callback


def _call_with_optional_progress(method, *args, progress_callback=None):
    if progress_callback is None:
        return method(*args)
    try:
        return method(*args, progress_callback=progress_callback)
    except TypeError as exc:
        if "progress_callback" not in str(exc):
            raise
        return method(*args)


def _ensure_timing(timing: dict | None) -> dict:
    per_stage = dict((timing or {}).get("per_stage_time_sec") or {})
    aliases = {
        "pages_render_time": "pages_render_time",
        "text_layer_time": "text_layer_time",
        "ocr_time": "ocr_time",
        "formula_detection_time": "formula_detection_time",
        "formula_recognition_time": "formula_recognition_time",
        "graph_build_time": "graph_build_time",
        "export_time": "export_time",
    }
    for key in aliases:
        per_stage.setdefault(key, float((timing or {}).get(key) or 0.0))
    total = float((timing or {}).get("total_time_sec") or sum(per_stage.values()))
    return {
        "total_time_sec": round(total, 4),
        "per_stage_time_sec": {key: round(float(value), 4) for key, value in per_stage.items()},
        **{key: round(float(per_stage.get(key, 0.0)), 4) for key in aliases},
    }


def _build_timing(stage_times: dict[str, float], total_started_at: float) -> dict:
    timing = _ensure_timing({"per_stage_time_sec": stage_times})
    timing["total_time_sec"] = round(time.perf_counter() - total_started_at, 4)
    return timing


def _build_processing_steps(result: ProcessingResult, ocr_mode: str) -> list[dict]:
    if result.processing_steps:
        return result.processing_steps
    text_sources = sorted({block.source for block in result.text_blocks})
    formula_sources = sorted({formula.source for formula in result.formulas})
    timing = _ensure_timing(result.timing)
    return [
        _step("upload", "ok" if result.filename else "error", "Загрузка документа", 1 if result.filename else 0, "hybrid"),
        _step("prepare_pages", "ok" if result.pages else "skipped", "Подготовка изображений страниц", len(result.pages), "text_layer", timing["pages_render_time"]),
        _step("text_layer", "ok" if result.text_blocks else "skipped", "Извлечение текстового слоя PDF", len(result.text_blocks), "text_layer", timing["text_layer_time"]),
        _step("ocr_fallback", "ok" if any(src in {"paddleocr", "tesseract", "got_ocr"} for src in text_sources) else "skipped", "Резервное OCR", len(result.text_blocks), "paddle/tesseract", timing["ocr_time"]),
        _step("formula_detection", "ok" if result.formulas else "partial", "Обнаружение формул", len(result.formulas), ",".join(formula_sources) or "hybrid", timing["formula_detection_time"]),
        _step("formula_classification", "ok" if any(formula.kind in {"inline", "block"} for formula in result.formulas) else "skipped", "Классификация строчных и блочных формул", len(result.formulas), "hybrid"),
        _step("latex_normalization", "ok" if any(formula.latex for formula in result.formulas) else "partial", "Нормализация LaTeX", sum(1 for formula in result.formulas if formula.latex), "tex_source" if "tex_source" in formula_sources else "hybrid"),
        _step("formula_masking", "ok" if result.formula_regions else "skipped", "Маскирование областей формул", len(result.formula_regions), "hybrid"),
        _step("token_reconstruction", "ok" if result.text_with_tokens else "partial", "Восстановление текста с формульными токенами", len(result.text_with_tokens), "hybrid"),
        _step("entity_extraction", "ok" if result.entities else "partial", "Извлечение сущностей", len(result.entities), "rule_based"),
        _step("context_linking", "ok" if result.relations else "partial", "Связывание формул с контекстом", len(result.relations), "rule_based"),
        _step("graph_build", "ok" if result.graph.nodes else "partial", "Построение графа", len(result.graph.nodes), "hybrid", timing["graph_build_time"]),
        _step("metagraph_build", "ok" if result.metagraph.nodes else "partial", "Построение расширенного метаграфа", len(result.metagraph.nodes), "hybrid"),
        _step("exports", "ok" if result.result_path else "partial", "Генерация JSON-экспортов", 1 if result.result_path else 0, "hybrid", timing["export_time"]),
        _step("visualization", "ok", "Генерация данных визуализации", len(result.graph.nodes) + len(result.metagraph.nodes), "hybrid"),
    ]


def _step(stage: str, status: str, description: str, count: int, source: str, duration: float = 0.0) -> dict:
    return {
        "stage": stage,
        "status": status,
        "description": description,
        "count": count,
        "source": source,
        "warnings": [],
        "duration_sec": round(float(duration or 0.0), 4),
    }
