import pytest


@pytest.fixture(autouse=True)
def offline_model(monkeypatch):
    """Unit tests never call a real model, even when the shell sets AP_LLM_MODEL."""
    monkeypatch.delenv("AP_LLM_MODEL", raising=False)
