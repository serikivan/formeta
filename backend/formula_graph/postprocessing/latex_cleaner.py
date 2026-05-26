from __future__ import annotations

import html
import re
from typing import Any


ZERO_WIDTH_RE = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2060\ufeff]")
CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
FENCE_RE = re.compile(r"^\s*```(?:tex|latex|math)?\s*|\s*```\s*$", re.IGNORECASE)
PREFIX_RE = re.compile(r"^\s*(?:latex|tex|formula|mfr|ocr)\s*:\s*", re.IGNORECASE)
SIMPLE_SCRIPT_RE = re.compile(r"(?<!\\)([A-Za-z0-9\)\]])([\^_])([A-Za-z0-9])\b")

LATEX_TEXT_COMMANDS = {
    "alpha": "alpha",
    "beta": "beta",
    "gamma": "gamma",
    "delta": "delta",
    "epsilon": "epsilon",
    "varepsilon": "epsilon",
    "zeta": "zeta",
    "eta": "eta",
    "theta": "theta",
    "vartheta": "theta",
    "iota": "iota",
    "kappa": "kappa",
    "lambda": "lambda",
    "mu": "mu",
    "nu": "nu",
    "xi": "xi",
    "pi": "pi",
    "rho": "rho",
    "varrho": "rho",
    "sigma": "sigma",
    "varsigma": "sigma",
    "tau": "tau",
    "upsilon": "upsilon",
    "phi": "phi",
    "varphi": "phi",
    "chi": "chi",
    "psi": "psi",
    "omega": "omega",
    "Gamma": "capital gamma",
    "Delta": "capital delta",
    "Theta": "capital theta",
    "Lambda": "capital lambda",
    "Xi": "capital xi",
    "Pi": "capital pi",
    "Sigma": "capital sigma",
    "Phi": "capital phi",
    "Psi": "capital psi",
    "Omega": "capital omega",
    "sum": "sum",
    "prod": "product",
    "coprod": "coproduct",
    "int": "integral",
    "iint": "double integral",
    "iiint": "triple integral",
    "oint": "contour integral",
    "lim": "limit",
    "limsup": "limit superior",
    "liminf": "limit inferior",
    "sup": "supremum",
    "inf": "infimum",
    "min": "minimum",
    "max": "maximum",
    "argmin": "arg minimum",
    "argmax": "arg maximum",
    "sin": "sine",
    "cos": "cosine",
    "tan": "tangent",
    "cot": "cotangent",
    "sec": "secant",
    "csc": "cosecant",
    "arcsin": "arcsine",
    "arccos": "arccosine",
    "arctan": "arctangent",
    "sinh": "hyperbolic sine",
    "cosh": "hyperbolic cosine",
    "tanh": "hyperbolic tangent",
    "log": "logarithm",
    "ln": "natural logarithm",
    "lg": "logarithm",
    "exp": "exponential",
    "det": "determinant",
    "dim": "dimension",
    "rank": "rank",
    "ker": "kernel",
    "deg": "degree",
    "gcd": "greatest common divisor",
    "Pr": "probability",
    "forall": "for all",
    "exists": "there exists",
    "nexists": "there does not exist",
    "in": "in",
    "notin": "not in",
    "ni": "contains",
    "subset": "subset",
    "subseteq": "subset or equal",
    "supset": "superset",
    "supseteq": "superset or equal",
    "cup": "union",
    "cap": "intersection",
    "setminus": "set difference",
    "emptyset": "empty set",
    "varnothing": "empty set",
    "land": "and",
    "lor": "or",
    "neg": "not",
    "Rightarrow": "implies",
    "Leftarrow": "is implied by",
    "Leftrightarrow": "if and only if",
    "to": "to",
    "mapsto": "maps to",
    "rightarrow": "to",
    "leftarrow": "from",
    "leftrightarrow": "leftrightarrow",
    "uparrow": "up",
    "downarrow": "down",
    "le": "less than or equal to",
    "ge": "greater than or equal to",
    "lt": "less than",
    "gt": "greater than",
    "ne": "not equal to",
    "approx": "approximately equal to",
    "sim": "similar to",
    "simeq": "similar or equal to",
    "equiv": "equivalent to",
    "cong": "congruent to",
    "propto": "proportional to",
    "pm": "plus or minus",
    "mp": "minus or plus",
    "cdot": "times",
    "times": "times",
    "div": "divided by",
    "ast": "asterisk",
    "star": "star",
    "circ": "composition",
    "bullet": "bullet",
    "oplus": "direct sum",
    "otimes": "tensor product",
    "odot": "odot",
    "wedge": "wedge",
    "vee": "vee",
    "partial": "partial",
    "nabla": "nabla",
    "grad": "gradient",
    "infty": "infinity",
    "ldots": "dots",
    "cdots": "dots",
    "vdots": "vertical dots",
    "ddots": "diagonal dots",
}

SYMBOL_TEXT_REPLACEMENTS = {
    "=": " equals ",
    "+": " plus ",
    "-": " minus ",
    "*": " times ",
    "/": " divided by ",
    "<": " less than ",
    ">": " greater than ",
    "≤": " less than or equal to ",
    "≥": " greater than or equal to ",
    "≠": " not equal to ",
    "≈": " approximately equal to ",
    "∈": " in ",
    "∉": " not in ",
    "⊂": " subset ",
    "⊆": " subset or equal ",
    "∪": " union ",
    "∩": " intersection ",
    "→": " to ",
    "←": " from ",
    "↔": " if and only if ",
    "∞": " infinity ",
}

UNICODE_LATEX_REPLACEMENTS = {
    "∑": r"\sum",
    "∫": r"\int",
    "√": r"\sqrt",
    "α": r"\alpha",
    "β": r"\beta",
    "γ": r"\gamma",
    "λ": r"\lambda",
    "μ": r"\mu",
    "π": r"\pi",
    "≤": r"\le",
    "≥": r"\ge",
    "≠": r"\ne",
    "≈": r"\approx",
    "→": r"\to",
    "∞": r"\infty",
    "·": r"\cdot",
    "×": r"\times",
    "−": "-",
}


def clean_latex(raw_latex: str) -> str:
    value = remove_model_artifacts(raw_latex)
    value = normalize_latex_wrappers(value)
    value = _normalize_whitespace(value)
    return value


def normalize_latex(cleaned_latex: str) -> str:
    value = normalize_latex_wrappers(cleaned_latex)
    value = normalize_latex_commands(value)
    value = _brace_simple_scripts(value)
    value = _normalize_whitespace(value)
    return value


def latex_to_plain_text(normalized_latex: str) -> str:
    value = normalized_latex or ""
    value = re.sub(r"\\operatorname\*?\{([^{}]+)\}", lambda match: match.group(1).strip(), value)
    value = re.sub(r"\\(?:mathrm|mathit|mathbf|mathsf|mathtt|text)\{([^{}]*)\}", lambda match: match.group(1).strip(), value)
    value = re.sub(r"\\frac\{([^{}]+)\}\{([^{}]+)\}", r"\1 divided by \2", value)
    value = re.sub(r"\\sqrt\[(.*?)\]\{([^{}]+)\}", r"\1 root of \2", value)
    value = re.sub(r"\\sqrt\{([^{}]+)\}", r"square root of \1", value)
    value = re.sub(r"_\{([^{}]+)\}", r" subscript \1", value)
    value = re.sub(r"\^\{2\}", " squared", value)
    value = re.sub(r"\^\{3\}", " cubed", value)
    value = re.sub(r"\^\{([^{}]+)\}", r" to the power of \1", value)
    value = re.sub(r"_(\w+)", r" subscript \1", value)
    value = re.sub(r"\^(\w+)", r" to the power of \1", value)
    value = re.sub(r"\\begin\{([^{}]+)\}", r"begin \1", value)
    value = re.sub(r"\\end\{([^{}]+)\}", r"end \1", value)
    value = re.sub(r"\\left|\\right", "", value)
    for char, replacement in SYMBOL_TEXT_REPLACEMENTS.items():
        value = value.replace(char, replacement)
    value = re.sub(
        r"\\([A-Za-z]+)\*?",
        lambda match: f" {LATEX_TEXT_COMMANDS.get(match.group(1), match.group(1))} ",
        value,
    )
    value = re.sub(r"[{}]", " ", value)
    value = re.sub(r"([()\[\],;|])", r" \1 ", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def remove_model_artifacts(text: str) -> str:
    value = "" if text is None else str(text)
    value = html.unescape(value)
    value = value.replace("\ufffd", "")
    value = ZERO_WIDTH_RE.sub("", value)
    value = CONTROL_RE.sub("", value)
    value = FENCE_RE.sub("", value.strip())
    value = PREFIX_RE.sub("", value)
    value = re.sub(r"</?(?:latex|tex|formula|math)>", "", value, flags=re.IGNORECASE)
    value = re.sub(r"\[(?:latex|tex|formula|math|ocr|mfr)\]", "", value, flags=re.IGNORECASE)
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value = re.sub(r"\n{2,}", "\n", value)
    value = re.sub(r"\\\\(?=[A-Za-z])", r"\\", value)
    return value.strip()


def normalize_latex_wrappers(text: str) -> str:
    value = remove_model_artifacts(text)
    previous = None
    while previous != value:
        previous = value
        value = value.strip()
        value = re.sub(r"^\$\$\s*(.*?)\s*\$\$$", r"\1", value, flags=re.DOTALL)
        value = re.sub(r"^\$\s*(.*?)\s*\$$", r"\1", value, flags=re.DOTALL)
        value = re.sub(r"^\\\[\s*(.*?)\s*\\\]$", r"\1", value, flags=re.DOTALL)
        value = re.sub(r"^\\\(\s*(.*?)\s*\\\)$", r"\1", value, flags=re.DOTALL)
    return value.strip()


def normalize_latex_commands(text: str) -> str:
    value = text or ""
    for old, new in UNICODE_LATEX_REPLACEMENTS.items():
        value = value.replace(old, new)
    value = re.sub(r"\\left\s*", "", value)
    value = re.sub(r"\\right\s*", "", value)
    value = value.replace(r"\leq", r"\le")
    value = value.replace(r"\geq", r"\ge")
    value = value.replace(r"\neq", r"\ne")
    value = re.sub(r"\\mbox\s*\{([^{}]*)\}", r"\\text{\1}", value)
    value = re.sub(r"\\operatorname\*\s*\{\s*l\s*i\s*m\s*\}", r"\\lim", value)
    value = re.sub(r"\\operatorname\s*\{\s*l\s*i\s*m\s*\}", r"\\lim", value)
    return value.strip()


def validate_latex_sanity(latex: str) -> dict[str, Any]:
    warnings: list[str] = []
    value = latex or ""
    if not value.strip():
        warnings.append("empty_latex")
    if _unbalanced(value, "{", "}"):
        warnings.append("unbalanced_braces")
    if _unbalanced(value, "(", ")"):
        warnings.append("unbalanced_parentheses")
    if "\ufffd" in value:
        warnings.append("replacement_symbol")
    if not re.search(r"\\[A-Za-z]+|[=<>_^]|\d|[\u0370-\u03ff]", value):
        warnings.append("weak_math_signal")
    score = max(0.0, 1.0 - 0.18 * len(warnings))
    return {"valid": not any(item in warnings for item in ("empty_latex", "unbalanced_braces")), "warnings": warnings, "score": round(score, 2)}


def build_latex_variants(raw_latex: str) -> dict[str, Any]:
    cleaned = clean_latex(raw_latex)
    normalized = normalize_latex(cleaned)
    return {
        "raw_latex": "" if raw_latex is None else str(raw_latex),
        "cleaned_latex": cleaned,
        "normalized_latex": normalized,
        "plain_formula_text": latex_to_plain_text(normalized),
        "sanity": validate_latex_sanity(normalized),
    }


def _brace_simple_scripts(value: str) -> str:
    def replace(match: re.Match[str]) -> str:
        base, operator, script = match.groups()
        return f"{base}{operator}{{{script}}}"

    previous = None
    while previous != value:
        previous = value
        value = SIMPLE_SCRIPT_RE.sub(replace, value)
    return value


def _normalize_whitespace(value: str) -> str:
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"\s+", " ", value)
    value = re.sub(r"([(\[{])\s+", r"\1", value)
    value = re.sub(r"\s+([)\]}])", r"\1", value)
    return value.strip()


def _unbalanced(value: str, left: str, right: str) -> bool:
    balance = 0
    escaped = False
    for char in value:
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == left:
            balance += 1
        elif char == right:
            balance -= 1
            if balance < 0:
                return True
    return balance != 0
