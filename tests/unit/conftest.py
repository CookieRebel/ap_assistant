import pytest


@pytest.fixture(autouse=True)
def isolated_from_env_file(tmp_path, monkeypatch):
    """Unit tests never call a real model and never read the repo's .env.

    The CLI loads .env from the current folder and lets it override the shell, so each test runs in its own
    empty folder, where there is no .env, with the offline model set.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AP_LLM_MODEL", "offline")
