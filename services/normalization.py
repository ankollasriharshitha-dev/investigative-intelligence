"""Deterministic MVP normalization for validated structured upload packages."""

import json
from pathlib import Path

import pandas as pd

from providers.synthetic import CSV_SCHEMAS, JSON_SCHEMAS


def normalize_package(package_dir: Path) -> None:
    """Normalize headers and textual values without fuzzy entity merging."""
    for filename in CSV_SCHEMAS:
        path = package_dir / filename
        frame = pd.read_csv(path)
        frame.columns = [str(column).strip() for column in frame.columns]
        for column in frame.columns:
            if frame[column].dtype == "object":
                frame[column] = frame[column].map(lambda value: value.strip() if isinstance(value, str) else value)
        frame.to_csv(path, index=False)
    for filename in JSON_SCHEMAS:
        path = package_dir / filename
        records = json.loads(path.read_text(encoding="utf-8"))
        path.write_text(json.dumps(records, indent=2), encoding="utf-8")
