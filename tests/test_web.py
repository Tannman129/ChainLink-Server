"""Web shell and local asset regressions; no application database required."""

from html.parser import HTMLParser
from importlib.resources import files

import pytest
from fastapi.testclient import TestClient

from app.main import app


class Assets(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in ("script", "img") and "src" in attrs:
            self.urls.append(attrs["src"])
        if tag == "link":
            self.urls.append(attrs["href"])


def test_dashboard_without_database(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with TestClient(app) as client:
        response = client.get("/")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/html")
        assert "ChainLink" in response.text
        assert 'id="main" tabindex="-1"' in response.text
        for page in (
            "dashboard",
            "courses",
            "layouts",
            "players",
            "rounds",
            "statistics",
        ):
            assert f'href="#{page}"' in response.text
        assert "script-src 'self'" in response.headers["content-security-policy"]
        assert response.headers["cache-control"] == "no-cache"
        parser = Assets()
        parser.feed(response.text)
        for url in parser.urls:
            assert url.startswith("/static/")
            assert client.get(url).status_code == 200


@pytest.mark.parametrize(
    "asset,media_type",
    [
        ("css/chainlink.css", "text/css"),
        ("js/chainlink.js", "javascript"),
        ("mark.svg", "image/svg+xml"),
        ("basket.svg", "image/svg+xml"),
        ("icons.svg", "image/svg+xml"),
        ("images/chainlink-basket.webp", "image/webp"),
        ("images/chainlink-favicon.png", "image/png"),
        ("images/chainlink-basket-small.webp", "image/webp"),
    ],
)
def test_static_assets_are_packaged(asset, media_type):
    assert files("app").joinpath("static", asset).is_file()
    with TestClient(app) as client:
        response = client.get(f"/static/{asset}")
        assert response.status_code == 200
        assert media_type in response.headers["content-type"]


def test_api_docs_and_unknown_paths_preserved():
    with TestClient(app) as client:
        assert client.get("/health").json()["status"] == "ok"
        assert client.get("/docs").status_code == 200
        assert client.get("/redoc").status_code == 200
        schema = client.get("/openapi.json").json()
        assert "/v1/courses/{course_id}/graph" in schema["paths"]
        assert "/" not in schema["paths"]
        assert client.get("/v1/unknown").status_code == 404
        assert client.get("/static/missing.js").status_code == 404
        assert client.get("/static/%2e%2e/config.py").status_code == 404
