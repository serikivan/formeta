from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Iterable


@dataclass(frozen=True)
class EvidenceRecord:
    symbol: str
    definition_text: str
    evidence: str
    language: str
    rule: str
    relation_type: str = "defined_as"
    confidence: float = 0.72
    scope: str = "paragraph"
    source: str = "rule_based"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


SYMBOL_RE = r"(?:\\?[A-Za-z](?:_\{?[A-Za-z0-9]+\}?)?|[A-Z]_[A-Za-z0-9]+|[Α-Ωα-ω])"
TAIL_RE = r"([^.;\n]{2,180})"

RU_RULES: tuple[tuple[str, str, float], ...] = (
    ("ru_where_dash", rf"(?:где)\s+(?P<symbol>{SYMBOL_RE})\s*(?:[-–—:])\s*(?P<definition>{TAIL_RE})", 0.78),
    ("ru_where_is", rf"(?:где)\s+(?P<symbol>{SYMBOL_RE})\s+(?:является|есть)\s+(?P<definition>{TAIL_RE})", 0.78),
    ("ru_denotes", rf"(?P<symbol>{SYMBOL_RE})\s+(?:обозначает|обозначают)\s+(?P<definition>{TAIL_RE})", 0.76),
    ("ru_named", rf"(?P<symbol>{SYMBOL_RE})\s+(?:называется|называют)\s+(?P<definition>{TAIL_RE})", 0.7),
    ("ru_defined_as", rf"(?P<symbol>{SYMBOL_RE})\s+(?:определяется\s+как|задается\s+как|задаётся\s+как)\s+(?P<definition>{TAIL_RE})", 0.8),
    ("ru_let", rf"(?:пусть)\s+(?P<symbol>{SYMBOL_RE})\s+(?P<definition>{TAIL_RE})", 0.64),
    ("ru_denote_by", rf"(?:через)\s+(?P<symbol>{SYMBOL_RE})\s+(?:обозначим|обозначается)\s+(?P<definition>{TAIL_RE})", 0.76),
    ("ru_is", rf"(?P<symbol>{SYMBOL_RE})\s*(?:[-–—])\s*это\s+(?P<definition>{TAIL_RE})", 0.74),
)

EN_RULES: tuple[tuple[str, str, float], ...] = (
    ("en_where_is", rf"(?:where)\s+(?P<symbol>{SYMBOL_RE})\s+(?:is|are)\s+(?P<definition>{TAIL_RE})", 0.78),
    ("en_denotes", rf"(?P<symbol>{SYMBOL_RE})\s+(?:denotes|denote)\s+(?P<definition>{TAIL_RE})", 0.76),
    ("en_defined_as", rf"(?P<symbol>{SYMBOL_RE})\s+(?:is|are)\s+defined\s+as\s+(?P<definition>{TAIL_RE})", 0.82),
    ("en_let_be", rf"(?:let)\s+(?P<symbol>{SYMBOL_RE})\s+(?:be)\s+(?P<definition>{TAIL_RE})", 0.72),
    ("en_represents", rf"(?P<symbol>{SYMBOL_RE})\s+(?:represents|represent)\s+(?P<definition>{TAIL_RE})", 0.74),
    ("en_denote_by", rf"(?:we\s+denote\s+by)\s+(?P<symbol>{SYMBOL_RE})\s+(?P<definition>{TAIL_RE})", 0.76),
)


def extract_definition_evidence(text: str, symbols: Iterable[str] | None = None) -> list[EvidenceRecord]:
    """Extract compact RU/EN scientific definition evidence records."""
    text = _normalize_text(text)
    if not text:
        return []
    allowed = {_normalize_symbol(symbol) for symbol in symbols or [] if _normalize_symbol(symbol)}
    records: list[EvidenceRecord] = []
    for language, rules in (("ru", RU_RULES), ("en", EN_RULES)):
        for rule_name, pattern, confidence in rules:
            for match in re.finditer(pattern, text, flags=re.IGNORECASE | re.UNICODE):
                symbol = _normalize_symbol(match.group("symbol"))
                if allowed and symbol not in allowed and symbol.lstrip("\\") not in allowed:
                    continue
                definition = _clean_definition(match.group("definition"))
                if not symbol or not definition:
                    continue
                records.append(
                    EvidenceRecord(
                        symbol=symbol,
                        definition_text=definition,
                        evidence=_normalize_text(match.group(0)),
                        language=language,
                        rule=rule_name,
                        confidence=confidence,
                    )
                )
    return _dedupe_records(records)


def _clean_definition(value: str) -> str:
    value = _normalize_text(value)
    value = re.sub(r"^(?:is|are|является|есть)\s+", "", value, flags=re.IGNORECASE)
    return value.strip(" ,:-–—")


def _normalize_symbol(value: str) -> str:
    value = str(value or "").strip().strip("$")
    value = value.replace("{", "").replace("}", "")
    return re.sub(r"\s+", "", value)


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _dedupe_records(records: list[EvidenceRecord]) -> list[EvidenceRecord]:
    result: list[EvidenceRecord] = []
    seen: set[tuple[str, str, str]] = set()
    for record in records:
        key = (record.symbol, record.definition_text.lower(), record.rule)
        if key in seen:
            continue
        seen.add(key)
        result.append(record)
    return result
