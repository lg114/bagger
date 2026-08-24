"""Tests for credential redaction and the API security boundary."""

from pathlib import Path

from fastapi.testclient import TestClient

from bagger.api.app import create_app
from bagger.config import Settings
from bagger.security import redact_secrets


def test_redact_secrets_covers_common_credentials():
    text = "token=abc123 password: hunter2 sk-proj-1234567890123456 AKIA1234567890ABCDEF"
    redacted = redact_secrets(text)
    assert "abc123" not in redacted
    assert "hunter2" not in redacted
    assert "sk-proj" not in redacted
    assert "AKIA" not in redacted


def test_api_token_protects_api_routes(monkeypatch, tmp_path: Path):
    import bagger.config as config

    monkeypatch.setattr(config, "settings", Settings(bagger_dir=tmp_path, api_token="test-token"))
    client = TestClient(create_app())
    assert client.get("/api/health").status_code == 401
    assert (
        client.get("/api/health", headers={"Authorization": "Bearer test-token"}).status_code == 200
    )
    assert client.options("/api/health").status_code != 401
