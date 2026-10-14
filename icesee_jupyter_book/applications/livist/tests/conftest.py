import pytest


@pytest.fixture(autouse=True)
def isolated_livist_settings(tmp_path, monkeypatch):
    """Tests never touch the host's LIVIST environment, database or workspaces
    unless they opt in (the integration test)."""
    monkeypatch.setenv("CRYOSTACK_LIVIST_ENV", str(tmp_path / "no-livist-env"))
    monkeypatch.setenv("CRYOSTACK_LIVIST_DATABASE", str(tmp_path / "var" / "livist.db"))
    monkeypatch.setenv("CRYOSTACK_WORKSPACE_ROOT", str(tmp_path / "workspaces"))
    monkeypatch.setenv("CRYOSTACK_LIVIST_INPUT_CACHE", str(tmp_path / "var" / "livist_input_cache"))
    # a small free-space reserve keeps the check active without depending on the host's disk
    monkeypatch.setenv("CRYOSTACK_LIVIST_JOB_RESERVE_MB", "1")
    for name in ("CRYOSTACK_LIVIST_INPUT_ROOTS", "CRYOSTACK_LIVIST_PUBLICATION_ENABLED",
                 "CRYOSTACK_LIVIST_PUBLICATION_PROFILE", "CRYOSTACK_LIVIST_MAX_ACTIVE",
                 "CRYOSTACK_LIVIST_JOB_TIMEOUT_S"):
        monkeypatch.delenv(name, raising=False)
