"""Practical, explainable entity extraction and cross-case matching."""

import re
import unicodedata
from collections.abc import Iterable
from typing import Any


PATTERNS = {
    "Phone": r"(?<!\w)(?:\+91[\s-]?)?[6-9]\d{9}(?!\w)",
    "Vehicle": r"\b[A-Z]{2}\s?\d{1,2}\s?[A-Z]{1,3}\s?\d{1,4}\b",
    "Email": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
    "Account": r"\b(?:ACC|A/C|ACCOUNT)[ -]?[A-Z0-9]{4,}\b",
    "Date": r"\b(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{2,4})\b",
}


def extract_entities(text: str, structured: dict[str, list[dict[str, Any]]] | None = None) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    for entity_type, pattern in PATTERNS.items():
        results.extend(_entity(entity_type, value) for value in re.findall(pattern, text or "", flags=re.IGNORECASE))
    # Conservative name/location cues avoid presenting NLP guesses as facts.
    for value in re.findall(r"\b(?:Mr\.?|Ms\.?|Officer)?\s*([A-Z][a-z]{2,}(?:\s+[A-Z][a-z]{2,}){1,2})\b", text or ""):
        if value not in {"The Same", "Case Evidence"}: results.append(_entity("Person", value))
    for value in re.findall(r"\b(?:near|at|in)\s+([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+){0,2})\b", text or ""):
        results.append(_entity("Location", value))
    for table, rows in (structured or {}).items():
        entity_type, field = {"persons": ("Person", "name"), "phones": ("Phone", "phone_number"), "vehicles": ("Vehicle", "registration_number"), "locations": ("Location", "label"), "organizations": ("Organization", "name"), "accounts": ("Account", "account_label")}.get(table, (None, None))
        if entity_type:
            results.extend(_entity(entity_type, str(row.get(field, ""))) for row in rows if row.get(field))
    unique = {(item["type"], item["normalized"]): item for item in results if item["normalized"]}
    return list(unique.values())


def normalize(value: str, entity_type: str) -> str:
    value = unicodedata.normalize("NFKC", value).strip()
    if entity_type in {"Phone", "Vehicle", "Account"}: return re.sub(r"[^A-Z0-9]", "", value.upper()).removeprefix("91") if entity_type == "Phone" and re.sub(r"\D", "", value).startswith("91") and len(re.sub(r"\D", "", value)) == 12 else re.sub(r"[^A-Z0-9]", "", value.upper())
    if entity_type == "Email": return value.lower()
    return re.sub(r"\s+", " ", value).casefold()


def potential_matches(case_id: str, entities: Iterable[dict[str, str]], existing: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    matches = []
    for entity in entities:
        for other in existing:
            if other.get("case_id") == case_id or other.get("type") != entity["type"]: continue
            if other.get("normalized") == entity["normalized"]:
                matches.append({"source_case": case_id, "target_case": other["case_id"], "entity": entity["value"], "entity_type": entity["type"], "reason": f"Same normalized {entity['type'].lower()} value.", "confidence": "High", "status": "Requires Investigator Verification", "evidence_id": other.get("evidence_id", "Synthetic dataset")})
    unique = {(x["target_case"], x["entity_type"], x["entity"]): x for x in matches}
    return list(unique.values())


def _entity(entity_type: str, value: str) -> dict[str, str]:
    return {"type": entity_type, "value": value.strip(), "normalized": normalize(value, entity_type)}
