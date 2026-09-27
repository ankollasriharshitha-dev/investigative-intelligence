"""Local case and intelligence persistence that can be replaced by a database repository."""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from services.audit import AuditService
from services.entity_intelligence import extract_entities, normalize, potential_matches


class CaseManagementService:
    def __init__(self, path: Path, audit: AuditService) -> None:
        self.path, self.audit = path, audit

    def cases(self) -> list[dict[str, Any]]:
        raw_cases = self._read().get("cases", [])
        enriched = []
        for c in raw_cases:
            item = dict(c)
            item.setdefault("department", "General Investigation Division")
            item.setdefault("investigating_officer", item.get("created_by", "Unassigned"))
            item.setdefault("assigned_users", [item.get("created_by", "demo_investigator")])
            item.setdefault("updated_at", item.get("created_at", _now()))
            enriched.append(item)
        return enriched

    def get_case(self, case_id: str) -> dict[str, Any] | None:
        for case in self.cases():
            if case.get("case_id") == case_id:
                return case
        return None

    def create(
        self,
        case_id: str,
        title: str,
        description: str,
        date: str,
        priority: str,
        user: str,
        department: str = "General Investigation Division",
        investigating_officer: str = "",
        assigned_users: list[str] | None = None,
    ) -> dict[str, Any]:
        if not case_id.strip() or not title.strip():
            raise ValueError("Case ID and title are required.")
        state = self._read()
        if any(case["case_id"] == case_id.strip() for case in state["cases"]):
            raise ValueError("A case with this ID already exists.")
        now_str = _now()
        record = {
            "case_id": case_id.strip(),
            "title": title.strip(),
            "description": description.strip(),
            "department": department.strip() if department else "General Investigation Division",
            "investigating_officer": investigating_officer.strip() or user,
            "assigned_users": assigned_users or [user],
            "opened_date": date,
            "priority": priority,
            "status": "Open",
            "created_by": user,
            "created_at": now_str,
            "updated_at": now_str,
        }
        state["cases"].append(record)
        self._write(state)
        self.audit.record(user, "CASE_CREATION", record["case_id"], "Success", {"title": record["title"], "department": record["department"]})
        return record

    def update(self, case_id: str, changes: dict[str, Any], user: str) -> dict[str, Any]:
        state = self._read()
        record = next((x for x in state["cases"] if x["case_id"] == case_id), None)
        if not record:
            raise ValueError("Case was not found.")
        allowed_keys = {"title", "description", "status", "priority", "department", "investigating_officer", "assigned_users"}
        record.update({key: value for key, value in changes.items() if key in allowed_keys})
        record["updated_at"] = _now()
        self._write(state)
        self.audit.record(user, "CASE_UPDATE", case_id, "Success", {"updated_fields": list(changes.keys())})
        return record

    def evidence_entities(self, evidence: dict[str, Any]) -> list[dict[str, str]]:
        entities = extract_entities(evidence.get("extracted_text", ""), evidence.get("entities", {}))
        state = self._read(); state["entities"] = [x for x in state["entities"] if x.get("evidence_id") != evidence["evidence_id"]]
        state["entities"].extend([{**item, "case_id": evidence["case_id"], "evidence_id": evidence["evidence_id"]} for item in entities])
        self._write(state)
        return entities

    def entity_records(self) -> list[dict[str, Any]]: return self._read().get("entities", [])

    def matches(self, case_id: str, entities: list[dict[str, str]], synthetic_entities: list[dict[str, Any]]) -> list[dict[str, Any]]:
        matches = potential_matches(case_id, entities, [*self.entity_records(), *synthetic_entities])
        state = self._read(); state["matches"] = [x for x in state["matches"] if x.get("source_case") != case_id] + matches; self._write(state)
        return matches

    def matches_for_case(self, case_id: str | None = None) -> list[dict[str, Any]]:
        rows = self._read().get("matches", []); return [x for x in rows if not case_id or x["source_case"] == case_id]

    def _read(self) -> dict[str, list]:
        if not self.path.exists(): return {"cases": [], "entities": [], "matches": []}
        try:
            value = json.loads(self.path.read_text(encoding="utf-8")); return {key: value.get(key, []) for key in ("cases", "entities", "matches")}
        except (OSError, json.JSONDecodeError): return {"cases": [], "entities": [], "matches": []}

    def _write(self, data: dict[str, list]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True); self.path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _now() -> str: return datetime.now(timezone.utc).isoformat(timespec="seconds")
