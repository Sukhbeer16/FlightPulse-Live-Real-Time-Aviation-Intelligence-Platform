"""Never let alert contract tests mutate the operator's persisted inbox."""
import pytest
from backend.app.config.settings import Settings
from backend.app.services import alerts


@pytest.fixture(autouse=True)
def isolated_alert_store(tmp_path, monkeypatch):
    settings = Settings(data_directory=tmp_path, _env_file=None)
    monkeypatch.setattr(alerts, "get_settings", lambda: settings)
