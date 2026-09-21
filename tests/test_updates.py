import json
import urllib.error

import pytest

from app.core import updates
from app.core.version import APP_VERSION


class _Response:
    def __init__(self, payload):
        self._body = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _reply(monkeypatch, payload):
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: _Response(payload))


def test_a_newer_tag_is_an_update(monkeypatch):
    _reply(monkeypatch, {"tag_name": "v99.0.0", "html_url": "https://example.test/r"})
    result = updates.check_for_update("1.2.3")
    assert result == {"version": "1.2.3", "latest": "99.0.0", "release_url": "https://example.test/r", "update_available": True}


@pytest.mark.parametrize("tag", ["v1.2.3", "v1.2.0", "v0.9.9"])
def test_the_same_or_an_older_tag_is_not_an_update(monkeypatch, tag):
    _reply(monkeypatch, {"tag_name": tag, "html_url": "u"})
    assert updates.check_for_update("1.2.3")["update_available"] is False


def test_versions_compare_numerically_not_as_text():
    assert updates.is_newer("0.17.10", "0.17.9") is True  # as text "10" < "9"
    assert updates.is_newer("0.17.9", "0.17.10") is False


def test_every_kind_of_failure_reports_no_update(monkeypatch):
    def offline(*a, **k):
        raise urllib.error.URLError("no network")

    monkeypatch.setattr("urllib.request.urlopen", offline)
    assert updates.check_for_update("1.0.0")["update_available"] is False
    _reply(monkeypatch, b"{ not json")
    assert updates.check_for_update("1.0.0")["update_available"] is False
    _reply(monkeypatch, ["not", "a", "dict"])
    assert updates.check_for_update("1.0.0")["update_available"] is False
    _reply(monkeypatch, {"tag_name": ""})
    assert updates.check_for_update("1.0.0")["latest"] is None


def test_the_shared_version_is_the_repo_version_file():
    from pathlib import Path

    expected = (Path(__file__).resolve().parent.parent / "VERSION").read_text(encoding="utf-8").strip()
    assert APP_VERSION == expected
