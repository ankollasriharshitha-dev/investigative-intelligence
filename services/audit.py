"""Append-only local audit log for the Phase-2 prototype."""

import json
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any


class AuditService:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = Lock()

    def record(self, user: str, action: str, resource: str, status: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        event = {"timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"), "user": user or "anonymous", "action": action, "resource": resource, "status": status, "metadata": metadata or {}}
        with self._lock:
            records = self.events()
            records.append(event)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(records, indent=2), encoding="utf-8")
        return event

    def events(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        try:
            content = json.loads(self.path.read_text(encoding="utf-8"))
            return content if isinstance(content, list) else []
        except (OSError, json.JSONDecodeError):
            return []
