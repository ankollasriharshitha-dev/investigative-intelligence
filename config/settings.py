"""Application configuration and filesystem locations."""

from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Settings:
    project_root: Path
    synthetic_data_dir: Path
    uploads_data_dir: Path


def get_settings() -> Settings:
    return Settings(
        project_root=PROJECT_ROOT,
        synthetic_data_dir=PROJECT_ROOT / "data" / "synthetic",
        uploads_data_dir=PROJECT_ROOT / "data" / "uploads",
    )
