from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def create_demo_summary(metadata: dict[str, Any], variable_search_result: dict[str, Any] | None, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    files = metadata.get("generated_files", [])
    lines = [
        "# Demo Summary",
        "",
        "## Document",
        f"- pages: {metadata.get('pages', 0)}",
        f"- formulas: {metadata.get('formulas', 0)}",
        f"- variables: {metadata.get('variables', 0)}",
        f"- meta nodes: {metadata.get('meta_nodes', 0)}",
        f"- meta edges: {metadata.get('meta_edges', 0)}",
        "",
        "## Variable search",
    ]
    if variable_search_result:
        lines.extend(
            [
                f"- variable: {variable_search_result.get('variable')}",
                f"- found formulas: {len(variable_search_result.get('formulas', []))}",
            ]
        )
    else:
        lines.append("- not requested")
    lines.extend(["", "## Main formula links"])
    for edge in metadata.get("main_links", [])[:20]:
        variable = f" by variable {edge.get('variable')}" if edge.get("variable") else ""
        lines.append(f"- {edge.get('source')} linked with {edge.get('target')} via {edge.get('relation')}{variable}")
    lines.extend(["", "## Generated files"])
    lines.extend(f"- {name}" for name in files)
    (output_dir / "demo_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def save_variable_search_result(result: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "variable_search_result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
