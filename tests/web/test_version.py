import json
import urllib.error

from fastapi.testclient import TestClient

from web.backend import appinfo
from web.backend.main import app

client = TestClient(app)


class _FakeResponse:
    def __init__(self, payload: dict):
        self._body = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


def test_version_reports_no_update_when_network_unavailable(monkeypatch):
    def _raise(*args, **kwargs):
        raise urllib.error.URLError("no network")

    monkeypatch.setattr("urllib.request.urlopen", _raise)

    response = client.get("/api/version")

    assert response.status_code == 200
    data = response.json()
    assert data["version"] == appinfo.APP_VERSION
    assert data["latest"] is None
    assert data["update_available"] is False


def test_version_reports_update_available_for_newer_tag(monkeypatch):
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *a, **k: _FakeResponse({"tag_name": "v99.99.99", "html_url": "https://example.com/release"}),
    )

    response = client.get("/api/version")

    data = response.json()
    assert data["latest"] == "99.99.99"
    assert data["release_url"] == "https://example.com/release"
    assert data["update_available"] is True


def test_version_reports_no_update_for_same_version(monkeypatch):
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *a, **k: _FakeResponse({"tag_name": f"v{appinfo.APP_VERSION}", "html_url": "https://example.com"}),
    )

    response = client.get("/api/version")

    data = response.json()
    assert data["latest"] == appinfo.APP_VERSION
    assert data["update_available"] is False


def test_version_handles_malformed_response(monkeypatch):
    class _BadResponse:
        def read(self):
            return b"not json"

        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return False

    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: _BadResponse())

    response = client.get("/api/version")

    assert response.status_code == 200
    assert response.json()["update_available"] is False
