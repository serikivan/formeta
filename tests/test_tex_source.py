from backend.formula_graph.layout.tex_source import align_tex_formulas, extract_tex_formulas
from backend.formula_graph.layout.tex_document import parse_tex_document
from backend.formula_graph.models import FormulaBlock
from backend.formula_graph.pipeline import process_document


def test_extract_tex_formulas_from_arxiv_source(tmp_path):
    source = tmp_path / "main.tex"
    source.write_text(
        r"""
        \documentclass{article}
        \begin{document}
        Inline $E = mc^2$ text.
        \begin{equation}
        X=\varphi_0(X)\cup\varphi_1(X)
        \label{eq:x}
        \end{equation}
        \[
        y \in \mathbb{R}^n
        \]
        \end{document}
        """,
        encoding="utf-8",
    )

    formulas, warnings = extract_tex_formulas(tmp_path)

    assert warnings == []
    assert [(item.kind, item.latex, item.source) for item in formulas] == [
        ("inline", "E = mc^2", "tex_source"),
        ("block", r"X=\varphi_0(X)\cup\varphi_1(X)", "tex_source"),
        ("block", r"y \in \mathbb{R}^n", "tex_source"),
    ]


def test_align_tex_formulas_replaces_ocr_latex_but_keeps_geometry():
    ocr_formula = FormulaBlock(
        id="f_1",
        page_number=3,
        latex=r"X = \phi_0(X) \cup \phi_1(X)",
        kind="block",
        bbox=(10, 20, 100, 40),
        source="pp_formula_net",
        confidence=0.82,
    )
    tex_formula = FormulaBlock(
        id="f_1",
        page_number=1,
        latex=r"X=\varphi_0(X)\cup\varphi_1(X)",
        kind="block",
        source="tex_source",
        confidence=0.99,
    )

    result = align_tex_formulas([ocr_formula], [tex_formula])

    assert len(result) == 1
    assert result[0].latex == r"X=\varphi_0(X)\cup\varphi_1(X)"
    assert result[0].bbox == (10, 20, 100, 40)
    assert result[0].page_number == 3
    assert result[0].source == "tex_source_aligned"
    assert result[0].raw_latex == r"X = \phi_0(X) \cup \phi_1(X)"
    assert "from_tex_source" in result[0].quality_flags


def test_align_tex_formulas_does_not_append_unmatched_by_default():
    ocr = [FormulaBlock(id="f_1", page_number=1, latex="s = -1/2 + i/2", kind="inline")]
    tex = [
        FormulaBlock(id="f_1", page_number=1, latex="s=-1/2+i/2", kind="inline"),
        FormulaBlock(id="f_2", page_number=1, latex=r"X=\varphi_0(X)", kind="block"),
    ]

    assert len(align_tex_formulas(ocr, tex)) == 1
    assert len(align_tex_formulas(ocr, tex, include_unmatched=True)) == 2


def test_align_tex_formulas_uses_similarity_not_global_order():
    ocr = [
        FormulaBlock(id="f_1", page_number=1, latex="s = -1/2 + i/2", kind="inline", source="text_inline_pattern"),
        FormulaBlock(id="f_2", page_number=1, latex=r"L = \psi_{0}(L) \cup \psi_{1}(L)", kind="inline", source="text_inline_pattern"),
    ]
    tex = [
        FormulaBlock(id="f_1", page_number=1, latex=r"\GG_1", kind="inline", source="tex_source"),
        FormulaBlock(id="f_2", page_number=1, latex="s=-1/2+i/2", kind="inline", source="tex_source"),
        FormulaBlock(id="f_3", page_number=1, latex=r"L=\psi_0(L)\cup\psi_1(L)", kind="inline", source="tex_source"),
    ]

    result = align_tex_formulas(ocr, tex)

    assert result[0].latex == "s=-1/2+i/2"
    assert result[1].latex == r"L=\psi_0(L)\cup\psi_1(L)"


def test_tex_parser_drops_tiny_inline_symbols(tmp_path):
    source = tmp_path / "main.tex"
    source.write_text(
        r"""
        \begin{document}
        Tiny $\psi_0$ should not become its own graph formula.
        Useful $L=\psi_0(L)\cup\psi_1(L)$ should stay.
        \end{document}
        """,
        encoding="utf-8",
    )

    formulas, _ = extract_tex_formulas(tmp_path)

    assert [formula.latex for formula in formulas] == [r"L=\psi_0(L)\cup\psi_1(L)"]


def test_tex_document_keeps_tiny_inline_math_as_text(tmp_path):
    (tmp_path / "main.tex").write_text(
        r"""
        \newcommand\GG{\mathcal{G}}
        \begin{document}
        We identify another directed graph $\GG_2$, that characterizes the translated curve.
        There exists a unique continuous solution $f(x)$.
        \end{document}
        """,
        encoding="utf-8",
    )

    document = parse_tex_document(tmp_path)
    text = " ".join(block.text for block in document.text_blocks)

    assert "graph G_2" in text
    assert "solution f(x)" in text
    assert "$" not in text
    assert document.formulas == []


def test_tex_document_expands_macros_in_formulas(tmp_path):
    (tmp_path / "main.tex").write_text(
        r"""
        \newcommand\GG{\mathcal{G}}
        \newcommand\NN{\mathbf{N}}
        \begin{document}
        A point is encoded by
        \[
        (x_i)_{i=1}^{\infty} \in \{0,1\}^{\NN}
        \]
        and follows the graph
        \[
        L=\left\{x : \mbox{ follows the directed-graph $\GG_1$} \right\}.
        \]
        \end{document}
        """,
        encoding="utf-8",
    )

    document = parse_tex_document(tmp_path)
    latex = "\n".join(formula.latex for formula in document.formulas)

    assert r"\NN" not in latex
    assert r"\GG" not in latex
    assert r"\mathbf{N}" in latex
    assert r"\mathcal{G}_1" in latex
    assert "$" not in latex


def test_tex_document_strips_figure_picture_noise(tmp_path):
    (tmp_path / "main.tex").write_text(
        r"""
        \begin{document}
        Clean paragraph before.
        \begin{figure}[H]
        \begin{center}
        \includegraphics[height=1.75in,width=.51\textwidth]{levydragonrotated.eps}
        \begin{picture}(320,180)(20,-120)
        \put(83,15){$q_0$}
        \line(1,-1){40}
        \end{picture}
        \caption{The first five steps}
        \end{center}
        \end{figure}
        Clean paragraph after.
        \end{document}
        """,
        encoding="utf-8",
    )

    document = parse_tex_document(tmp_path)
    text = " ".join(block.text for block in document.text_blocks)

    assert "Clean paragraph before" in text
    assert "Clean paragraph after" in text
    assert "levydragonrotated" not in text
    assert "picture" not in text
    assert "q_0" not in text


def test_prefer_tex_source_bypasses_render_and_ocr(tmp_path, monkeypatch):
    pdf_path = tmp_path / "2605.00001.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "main.tex").write_text(
        r"""
        \documentclass{article}
        \begin{document}
        \section{Model}
        Let \lambda denote the wavelength.
        \[
        \lambda = \frac{c}{f}
        \]
        where c denotes speed and f denotes frequency.
        \end{document}
        """,
        encoding="utf-8",
    )

    def fail_render(*args, **kwargs):
        raise AssertionError("render_document must not run for TeX source processing")

    monkeypatch.setattr("backend.formula_graph.pipeline.render_document", fail_render)
    monkeypatch.setattr("backend.formula_graph.pipeline.fetch_arxiv_source", lambda tex_id, document_id: (source_dir, []))

    result = process_document(
        pdf_path,
        "2605.00001.pdf",
        ocr_mode="auto",
        device_mode="cpu",
        arxiv_id="2605.00001",
        prefer_tex_source=True,
        max_pages=1,
    )

    assert result.status == "ok"
    assert result.pages == []
    assert result.text_blocks
    assert result.formulas
    assert all(formula.source == "tex_source" for formula in result.formulas)
