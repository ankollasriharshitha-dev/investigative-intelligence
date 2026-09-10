"""Stable domain contracts shared by providers, services, and future frontends."""

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

import pandas as pd


class DataSourceType(StrEnum):
    SYNTHETIC = "synthetic_demo"
    UPLOADED = "uploaded_investigation"
    DATABASE = "database"
    API = "api"


@dataclass(frozen=True)
class DataSourceInfo:
    source_type: DataSourceType
    name: str
    location: Path | None
    is_active: bool = True


@dataclass
class DatasetSnapshot:
    """Normalized tables exposed to services, independent of their storage medium."""

    tables: dict[str, pd.DataFrame] = field(default_factory=dict)
    documents: dict[str, Any] = field(default_factory=dict)
    source: DataSourceInfo | None = None


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    checked_files: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class ImportReport:
    operation: str
    records_received: int
    records_added: int
    records_updated: int
    duplicates_skipped: int
    records_rejected: int
    validation: ValidationResult
    imported_at: str | None = None
    ingestion_id: str | None = None
    dataset_version: int | None = None


@dataclass(frozen=True)
class DatasetMetadata:
    dataset_id: str
    source: str
    version: int
    created_at: str
    updated_at: str
    record_count: int
    status: str
    validation_status: str


@dataclass(frozen=True)
class IngestionRecord:
    ingestion_id: str
    source: str
    operation: str
    timestamp: str
    records_received: int
    records_added: int
    records_updated: int
    records_rejected: int
    status: str
