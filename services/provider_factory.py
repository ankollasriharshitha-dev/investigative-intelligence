"""Composition root for selecting the active data provider."""

from config.settings import Settings
from providers.base import DataProvider
from providers.synthetic import SyntheticDataProvider
from providers.uploaded import UploadedDataProvider
from services.data_management import DataManagementService


def build_current_provider(settings: Settings) -> DataProvider:
    """Compose the provider selected by the persisted active-source registry."""
    manager = DataManagementService(settings)
    if manager.active_source_type() == "uploaded" and manager.uploaded_exists():
        state = manager._read_state()
        return UploadedDataProvider(manager.current_dir, state.get("imported_at"))
    return SyntheticDataProvider(settings.synthetic_data_dir)
