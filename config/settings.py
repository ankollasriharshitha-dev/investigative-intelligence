import os
from dataclasses import dataclass
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


PROJECT_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Settings:
    project_root: Path
    synthetic_data_dir: Path
    uploads_data_dir: Path
    runtime_data_dir: Path | None = None
    data_provider: str = "synthetic"
    database_url: str | None = None


def get_settings() -> Settings:
    provider = os.getenv("DATA_PROVIDER", "synthetic").lower().strip()
    db_url = os.getenv("DATABASE_URL")
    return Settings(
        project_root=PROJECT_ROOT,
        synthetic_data_dir=PROJECT_ROOT / "data" / "synthetic",
        uploads_data_dir=PROJECT_ROOT / "data" / "uploads",
        runtime_data_dir=PROJECT_ROOT / "data" / "runtime",
        data_provider=provider,
        database_url=db_url,
    )
