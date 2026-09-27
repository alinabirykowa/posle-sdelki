"""Keep cached HTML from pointing at removed assets after a deployment."""

import os
from importlib import import_module

from fastapi.testclient import TestClient


def test_equal_size_builds_with_normalized_mtime_have_different_validators(monkeypatch, tmp_path):
    app_module = import_module("backend.app")
    monkeypatch.setattr(app_module, "ROOT", tmp_path)
    dist = tmp_path / "frontend" / "dist"
    dist.mkdir(parents=True)
    index = dist / "index.html"
    old = '<html><script src="/assets/old.js"></script></html>'
    new = '<html><script src="/assets/new.js"></script></html>'
    assert len(old) == len(new)

    index.write_text(old)
    os.utime(index, (1540000000, 1540000000))
    with TestClient(app_module.create_app(tmp_path / "old.sqlite3")) as client:
        response = client.get("/")
        previous_tag = response.headers["etag"]
        assert response.status_code == 200

    index.write_text(new)
    os.utime(index, (1540000000, 1540000000))
    with TestClient(app_module.create_app(tmp_path / "new.sqlite3")) as client:
        for path in ("/", "/index.html", "/session/example"):
            response = client.get(path, headers={"If-None-Match": previous_tag, "If-Modified-Since": "Sat, 20 Oct 2018 01:46:40 GMT"})
            assert response.status_code == 200
            assert response.text == new
            assert response.headers["etag"] != previous_tag
            assert "last-modified" not in response.headers
            assert response.headers["cache-control"] == "no-cache"
        assert client.get("/api/unknown").status_code == 404
