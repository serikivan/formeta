from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from backend.formula_graph.config import settings
from backend.formula_graph.graph.demo_report import create_demo_summary, save_variable_search_result
from backend.formula_graph.graph.metagraph_validator import validate_metagraph
from backend.formula_graph.graph.semantic_metagraph import search_variable_context
from backend.formula_graph.graph.semantic_visualization import (
    generate_demo_dashboard,
    generate_formula_graph_view,
    generate_graph_view,
    generate_metagraph_view,
    generate_variable_focus_view,
    generate_variable_metagraph_view,
)
from backend.formula_graph.pipeline import process_document


RECOGNIZER_ALIASES = {
    "mock": "text_layer",
    "text-layer": "text_layer",
    "text_layer": "text_layer",
    "standard": "standard",
    "auto": "auto",
    "hybrid": "hybrid",
    "structure": "structure",
    "tesseract": "tesseract",
    "marker": "marker",
    "tex_source": "tex_source",
}


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    source = Path(args.pdf)
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    recognizer = RECOGNIZER_ALIASES.get(args.recognizer, args.recognizer)
    result = process_document(
        source,
        source.name,
        ocr_mode=recognizer,
        device_mode=args.device,
        max_pages=args.max_pages,
        render_dpi=args.render_dpi,
        prefer_tex_source=recognizer == "tex_source",
    )

    artifacts = _collect_artifacts(result.document_id)
    _write_standard_outputs(artifacts, output_dir)

    variable_search_result = None
    if args.search_variable:
        variable_search_result = _search_variable(args.search_variable, artifacts)
        save_variable_search_result(variable_search_result, output_dir)

    generated_files = [
        "graph_input.json",
        "metagraph.json",
        "metagraph_validation.json",
        "variable_index.json",
        "formulas.json",
        "formula_interpretations.json",
    ]
    if variable_search_result is not None:
        generated_files.append("variable_search_result.json")

    if args.visualize:
        generated_files.extend(_generate_visualizations(args, artifacts, output_dir))

    create_demo_summary(
        {
            "document_id": result.document_id,
            "status": result.status,
            "formulas": len(artifacts["formulas"]),
            "variables": len(artifacts["variable_index"]),
            "meta_nodes": len(artifacts["metagraph"].get("meta_nodes", [])),
            "meta_edges": len(artifacts["metagraph"].get("meta_edges", [])),
            "main_links": artifacts["metagraph"].get("meta_edges", []),
            "generated_files": generated_files,
        },
        variable_search_result,
        output_dir,
    )

    print(f"Document: {result.document_id}")
    print(f"Status: {result.status}")
    print(f"Formulas: {len(artifacts['formulas'])}")
    print(f"Variables: {len(artifacts['variable_index'])}")
    print(f"Meta nodes: {len(artifacts['metagraph'].get('meta_nodes', []))}")
    print(f"Meta edges: {len(artifacts['metagraph'].get('meta_edges', []))}")
    if variable_search_result is not None:
        print(f"Variable search: {args.search_variable} -> {len(variable_search_result.get('formulas', []))} formulas")
    print("Visualization:")
    for name in generated_files:
        if name.endswith(".html"):
            print(f"- {name}")
    print(f"Output: {output_dir}")
    return 0 if result.status != "error" else 1


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build formula graph, semantic metagraph, search index, and demo visualizations.")
    parser.add_argument("--pdf", required=True, help="Path to PDF or image document.")
    parser.add_argument("--output", default="output", help="Directory for standardized artifacts.")
    parser.add_argument("--recognizer", default="standard", help="Recognition mode: mock, standard, text_layer, auto, hybrid, structure, marker, tex_source.")
    parser.add_argument("--search-variable", default=None, help="Variable name for variable_index lookup and focused visualization.")
    parser.add_argument("--visualize", action="store_true", help="Generate HTML visualizations.")
    parser.add_argument("--visual-preset", default="defense", choices=["simple", "defense", "full", "variable"], help="Visualization preset.")
    parser.add_argument("--max-pages", type=int, default=0, help="Maximum pages to process; 0 means all pages.")
    parser.add_argument("--render-dpi", type=int, default=200, help="Render DPI for PDF pages.")
    parser.add_argument("--device", default="cpu", choices=["cpu", "gpu", "auto"], help="OCR/MFR device preference.")
    return parser.parse_args(argv)


def _collect_artifacts(document_id: str) -> dict[str, Any]:
    base = settings.results_dir
    graph_input = _read_json(base / f"{document_id}.graph_input.json", {"nodes": [], "edges": []})
    metagraph = _read_json(base / f"{document_id}.metagraph.json", {"nodes": [], "edges": [], "meta_nodes": [], "meta_edges": [], "statistics": {}})
    variable_index = _read_json(base / f"{document_id}.variable_index.json", {})
    formulas = _read_json(base / f"{document_id}.formulas.json", [])
    formula_interpretations = _read_json(base / f"{document_id}.formula_interpretations.json", [])
    validation_path = base / f"{document_id}.metagraph_validation.json"
    metagraph_validation = _read_json(validation_path, validate_metagraph(metagraph))
    return {
        "graph_input": graph_input,
        "metagraph": metagraph,
        "variable_index": variable_index,
        "formulas": formulas,
        "formula_interpretations": formula_interpretations,
        "metagraph_validation": metagraph_validation,
    }


def _write_standard_outputs(artifacts: dict[str, Any], output_dir: Path) -> None:
    _write_json(output_dir / "graph_input.json", {"nodes": artifacts["graph_input"].get("nodes", []), "edges": artifacts["graph_input"].get("edges", [])})
    _write_json(output_dir / "metagraph.json", artifacts["metagraph"])
    _write_json(output_dir / "metagraph_validation.json", artifacts["metagraph_validation"])
    _write_json(output_dir / "variable_index.json", artifacts["variable_index"])
    _write_json(output_dir / "formulas.json", artifacts["formulas"])
    _write_json(output_dir / "formula_interpretations.json", artifacts["formula_interpretations"])


def _search_variable(variable: str, artifacts: dict[str, Any]) -> dict[str, Any]:
    metagraph = artifacts["metagraph"]
    formulas = [node for node in metagraph.get("nodes", []) if node.get("type") == "formula"]
    contexts = [node for node in metagraph.get("nodes", []) if node.get("type") == "context"]
    return search_variable_context(variable, artifacts["variable_index"], formulas, contexts, metagraph)


def _generate_visualizations(args: argparse.Namespace, artifacts: dict[str, Any], output_dir: Path) -> list[str]:
    graph_input = {"nodes": artifacts["graph_input"].get("nodes", []), "edges": artifacts["graph_input"].get("edges", [])}
    metagraph = artifacts["metagraph"]
    variable_index = artifacts["variable_index"]

    generate_graph_view(graph_input, output_dir / "graph_view.html")
    generate_formula_graph_view(graph_input, output_dir / "formula_graph_view.html")
    generate_metagraph_view(metagraph, output_dir / "metagraph_view.html")

    generated = ["graph_view.html", "formula_graph_view.html", "metagraph_view.html"]
    if args.search_variable:
        suffix = _safe_filename(args.search_variable)
        generate_variable_metagraph_view(args.search_variable, metagraph, variable_index, output_dir / f"metagraph_variable_{suffix}.html")
        generate_variable_focus_view(args.search_variable, graph_input, metagraph, variable_index, output_dir / f"variable_focus_{suffix}.html")
        generated.extend([f"metagraph_variable_{suffix}.html", f"variable_focus_{suffix}.html"])

    generate_demo_dashboard(
        {
            "preset": args.visual_preset,
            "formulas": len(artifacts["formulas"]),
            "variables": len(variable_index),
            "meta_nodes": len(metagraph.get("meta_nodes", [])),
            "meta_edges": len(metagraph.get("meta_edges", [])),
            "generated_files": generated,
        },
        output_dir,
    )
    generated.append("demo_dashboard.html")
    return generated


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _safe_filename(value: str) -> str:
    value = str(value or "").strip().replace("\\", "")
    value = re.sub(r"\s+", "_", value)
    value = re.sub(r"[^\w\u0400-\u04FF]+", "_", value, flags=re.UNICODE)
    return value.strip("_") or "variable"


if __name__ == "__main__":
    raise SystemExit(main())
