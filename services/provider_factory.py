from config.settings import Settings
from database.connection import mask_database_url, test_connection
from providers.base import DataProvider
from providers.postgres import PostgresDataProvider
from providers.synthetic import SyntheticDataProvider
from providers.uploaded import UploadedDataProvider
from services.data_management import DataManagementService


def build_current_provider(settings: Settings) -> DataProvider:
    """Compose the provider selected by configuration or the persisted active-source registry."""
    if settings.data_provider in ("postgres", "database"):
        ok, msg = test_connection(settings.database_url)
        if not ok:
            masked = mask_database_url(settings.database_url)
            raise RuntimeError(
                f"PostgreSQL data provider is selected, but the database connection failed ({masked}). "
                f"Verify your PostgreSQL server and DATABASE_URL setting. Error details: {msg}"
            )
        return PostgresDataProvider(settings.database_url)

    manager = DataManagementService(settings)
    if manager.active_source_type() == "uploaded" and manager.uploaded_exists():
        state = manager._read_state()
        return UploadedDataProvider(manager.current_dir, state.get("imported_at"))
    return SyntheticDataProvider(settings.synthetic_data_dir)
