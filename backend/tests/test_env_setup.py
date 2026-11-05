"""Local dotenv startup behavior without credentials or provider requests."""

import os

from fastapi.testclient import TestClient

from app import main


def test_startup_loads_backend_env_from_another_directory(tmp_path, monkeypatch):
    backend = tmp_path / "backend"
    backend.mkdir()
    env_path = backend / ".env"
    env_path.write_text(
        "GEMINI_API_KEY=test-local-key\nGEMINI_MODEL=test-local-model\n",
        encoding="utf-8-sig",
    )
    monkeypatch.setattr(main, "BACKEND_ENV_PATH", env_path)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    monkeypatch.chdir(tmp_path)

    with TestClient(main.create_app()) as client:
        assert client.get("/health").json() == {"status": "ok"}
    assert os.environ["GEMINI_API_KEY"] == "test-local-key"
    assert os.environ["GEMINI_MODEL"] == "test-local-model"


def test_startup_preserves_existing_environment(tmp_path, monkeypatch):
    env_path = tmp_path / ".env"
    env_path.write_text("GEMINI_API_KEY=file-key\nGEMINI_MODEL=file-model\n")
    monkeypatch.setattr(main, "BACKEND_ENV_PATH", env_path)
    monkeypatch.setenv("GEMINI_API_KEY", "terminal-key")
    monkeypatch.setenv("GEMINI_MODEL", "terminal-model")

    main.create_app()

    assert os.environ["GEMINI_API_KEY"] == "terminal-key"
    assert os.environ["GEMINI_MODEL"] == "terminal-model"


def test_startup_without_env_file(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "BACKEND_ENV_PATH", tmp_path / "missing.env")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_MODEL", raising=False)

    with TestClient(main.create_app()) as client:
        assert client.get("/health").status_code == 200
    assert "GEMINI_API_KEY" not in os.environ
    assert "GEMINI_MODEL" not in os.environ
