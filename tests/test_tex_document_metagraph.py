from backend.formula_graph.graph.metagraph import build_metagraph
from backend.formula_graph.layout.tex_document import parse_tex_document
from backend.formula_graph.semantic.entities import bind_formulas_to_context, extract_entities


def test_parse_tex_document_builds_text_tokens_and_sections(tmp_path):
    source = tmp_path / "main.tex"
    source.write_text(
        r"""
        \documentclass{article}
        \begin{document}
        \section{Model}
        We define the transport equation
        \begin{equation}
        q_x = \rho u_i \Phi - E_{eff}\frac{\partial \Phi}{\partial x}
        \label{eq:transport}
        \end{equation}
        and use inline $E = mc^2$ as a check.
        \end{document}
        """,
        encoding="utf-8",
    )

    document = parse_tex_document(tmp_path)

    assert document.warnings == []
    assert [block.text for block in document.text_blocks if block.role == "section"] == ["Model"]
    assert [formula.kind for formula in document.formulas] == ["block", "inline"]
    assert document.formulas[0].label == "eq:transport"
    assert document.formulas[0].section_id == "sec_1"
    assert "[FORMULA_001]" in " ".join(block.text for block in document.text_with_tokens)
    assert all(block.text.strip(" .,;:!?") for block in document.text_with_tokens)


def test_parse_tex_document_extracts_front_matter_and_abstract(tmp_path):
    source = tmp_path / "main.tex"
    source.write_text(
        r"""
        \documentclass{article}
        \title{Shifted L\'evy's Dragon Curve and Directed Graph}
        \author{Jonathan Leung \\ University of North Texas \footnote{email}}
        \begin{document}
        \maketitle
        \begin{abstract}
        We study the translation by $s=-1/2+i/2$ and introduce a graph.
        \end{abstract}
        \section{Introduction}
        Body text.
        \begin{definition}
        A graph is directed if every edge has an orientation.
        \end{definition}
        \end{document}
        """,
        encoding="utf-8",
    )

    document = parse_tex_document(tmp_path)
    by_role = {block.role: block.text for block in document.text_blocks if block.role in {"title", "author", "abstract"}}
    text = " ".join(block.text for block in document.text_blocks)

    assert by_role["title"] == "Shifted Lévy's Dragon Curve and Directed Graph"
    assert "Jonathan Leung" in by_role["author"]
    assert "We study the translation by" in by_role["abstract"]
    assert [block.text for block in document.text_blocks if block.role == "section"] == ["Introduction"]
    assert "Definition. A graph is directed" in text


def test_parse_tex_document_keeps_formula_inside_paragraph(tmp_path):
    source = tmp_path / "main.tex"
    source.write_text(
        r"""
        \documentclass{article}
        \begin{document}
        We introduce the variable
        \[
        x = y + z
        \]
        and continue the same paragraph with its interpretation.
        \end{document}
        """,
        encoding="utf-8",
    )

    document = parse_tex_document(tmp_path)
    paragraphs = [block.text for block in document.text_with_tokens if block.role == "paragraph"]

    assert len(paragraphs) == 1
    assert "We introduce the variable [FORMULA_001] and continue" in paragraphs[0]


def test_build_metagraph_groups_tex_formulas_by_section(tmp_path):
    source = tmp_path / "main.tex"
    source.write_text(
        r"""
        \begin{document}
        \section{Model}
        Text before \[ a = b + c \]
        \subsection{Boundary}
        Boundary condition \[ u = 0 \]
        \end{document}
        """,
        encoding="utf-8",
    )
    document = parse_tex_document(tmp_path)
    entities, relations = extract_entities(document.text_blocks, document.formulas)
    relations.extend(bind_formulas_to_context(document.formulas, document.text_with_tokens))

    metagraph = build_metagraph("doc_1", document.text_blocks, document.formulas, entities, relations)

    kinds = {node.kind for node in metagraph.nodes}
    assert "meta_document" in kinds
    assert "meta_section" in kinds
    assert "meta_equation_group" in kinds
    assert "meta_variable_set" in kinds
    assert any(edge.label == "contains_equation_group" for edge in metagraph.edges)
    assert any(edge.label == "uses_variable" for edge in metagraph.edges)
