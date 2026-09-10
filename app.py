"""Streamlit entry point for the Investigative Intelligence platform."""

from config.settings import get_settings
from services.investigation import InvestigationService
from services.provider_factory import build_current_provider
from ui.shell import render_application



def main() -> None:
    settings = get_settings()
    provider = build_current_provider(settings)
    service = InvestigationService(provider, settings)
    render_application(service)


if __name__ == "__main__":
    main()
