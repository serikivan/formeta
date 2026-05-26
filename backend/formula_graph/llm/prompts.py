FORMULA_VERIFICATION_PROMPT = """Return strict JSON only. Verify or lightly repair the LaTeX candidate.

Allowed status values:
- "ok": corrected_latex is valid and can be used.
- "uncertain": you have a plausible suggestion, but evidence is weak.
- "failed": you cannot verify or repair the formula.
- "skipped": the input does not need refinement.

Rules:
- Do not use status "error"; use "failed" instead.
- corrected_latex must always be a string. If unchanged, repeat latex_candidate.
- changed must be true only when corrected_latex differs from latex_candidate.
- confidence must be a number from 0 to 1.
- Return JSON only, no markdown.

Required fields: status, corrected_latex, changed, confidence, reason, warnings, provider, model."""

CONTEXT_REFINEMENT_RU_PROMPT = """Верни только строгий JSON. Извлеки определения переменных из русского научного контекста."""

CONTEXT_REFINEMENT_EN_PROMPT = """Return strict JSON only. Extract variable definitions from English scientific context."""

VARIABLE_CONTEXT_SUMMARY_PROMPT = """Return strict JSON only. Summarize variable usage, scope, evidence, and confidence."""

CORPUS_CONFLICT_PROMPT = """Return strict JSON only. Compare variable meanings across documents and report possible conflicts."""
