"""Provider for the validated, separately stored uploaded investigation package."""

from pathlib import Path

from domain.models import DataSourceInfo, DataSourceType
from providers.synthetic import SyntheticDataProvider


class UploadedDataProvider(SyntheticDataProvider):
    """Reuse the internal package schema while exposing uploaded source metadata."""

    def __init__(self, data_dir: Path, imported_at: str | None = None) -> None:
        super().__init__(data_dir)
        self._source = DataSourceInfo(
            source_type=DataSourceType.UPLOADED,
            name="Uploaded Investigation Dataset",
            location=data_dir,
        )
        self.imported_at = imported_at