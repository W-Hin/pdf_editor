from fastapi import FastAPI
from fastapi.testclient import TestClient

from web.backend.main import mount_frontend


def _client_with_dist(tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html><body>app</body></html>", encoding="utf-8")
    (dist / "assets" / "index-abc123.js").write_text("console.log('x')", encoding="utf-8")
    app = FastAPI()
    mount_frontend(app, dist)
    return TestClient(app)


def test_index_html_must_be_revalidated_so_an_upgrade_never_shows_a_stale_app(tmp_path):
    client = _client_with_dist(tmp_path)
    response = client.get("/")
    assert response.status_code == 200
    assert "app" in response.text
    assert "no-cache" in response.headers["cache-control"]


def test_client_side_routes_also_serve_index_html_with_no_cache(tmp_path):
    client = _client_with_dist(tmp_path)
    response = client.get("/tool/merge")
    assert response.status_code == 200
    assert "no-cache" in response.headers["cache-control"]


def test_assets_are_still_served(tmp_path):
    client = _client_with_dist(tmp_path)
    response = client.get("/assets/index-abc123.js")
    assert response.status_code == 200
    assert "console.log" in response.text


def test_api_paths_never_fall_through_to_the_frontend(tmp_path):
    client = _client_with_dist(tmp_path)
    assert client.get("/api/nope").status_code == 404


def test_mount_frontend_is_a_no_op_when_the_frontend_is_not_built(tmp_path):
    app = FastAPI()
    mount_frontend(app, tmp_path / "missing")
    assert TestClient(app).get("/").status_code == 404
