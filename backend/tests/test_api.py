from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.db import Base, get_engine


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    from app.api import projects
    from app.main import app

    Base.metadata.drop_all(get_engine())
    Base.metadata.create_all(get_engine())
    enqueued: list[tuple[str, tuple[Any, ...]]] = []
    monkeypatch.setattr(projects, "enqueue", lambda q, f, *a, **k: enqueued.append((f, a)) or "job-1")
    with TestClient(app) as c:
        c.enqueued = enqueued  # type: ignore[attr-defined]
        yield c


def register(c: TestClient, email: str) -> None:
    r = c.post("/api/auth/register", json={"email": email, "password": "heslo12345"})
    assert r.status_code == 201, r.text


def test_auth_flow(client: TestClient) -> None:
    assert client.get("/api/auth/me").status_code == 401
    register(client, "Jana@Example.cz")
    assert client.get("/api/auth/me").json()["email"] == "jana@example.cz"
    assert client.post("/api/auth/register", json={"email": "jana@example.cz", "password": "heslo12345"}).status_code == 409
    client.post("/api/auth/logout")
    assert client.get("/api/auth/me").status_code == 401
    assert client.post("/api/auth/login", json={"email": "jana@example.cz", "password": "spatne"}).status_code == 401
    assert client.post("/api/auth/login", json={"email": "jana@example.cz", "password": "heslo12345"}).status_code == 200
    r = client.post("/api/auth/register", json={"email": "x@y.cz", "password": "short"})
    assert r.status_code == 422 and "Neplatná data" in r.json()["detail"]


def upload(c: TestClient, data: bytes, name: str = "video.mp4", chunk: int = 4) -> str:
    r = c.post("/api/uploads", json={"filename": name, "size": len(data)})
    assert r.status_code == 201, r.text
    uid = r.json()["id"]
    off = 0
    while off < len(data):
        r = c.put(f"/api/uploads/{uid}?offset={off}", content=data[off : off + chunk])
        assert r.status_code == 200, r.text
        off = r.json()["received"]
    assert r.json()["status"] == "complete"
    return str(uid)


def test_resumable_upload_and_project(client: TestClient) -> None:
    register(client, "a@example.cz")
    data = b"0123456789abcdef"
    r = client.post("/api/uploads", json={"filename": "film.mp4", "size": len(data)})
    uid = r.json()["id"]
    client.put(f"/api/uploads/{uid}?offset=0", content=data[:6])
    # client lost track and resends from a wrong offset -> 409 with the server position
    r = client.put(f"/api/uploads/{uid}?offset=10", content=data[10:])
    assert r.status_code == 409 and r.json()["detail"]["received"] == 6
    assert client.get(f"/api/uploads/{uid}").json()["received"] == 6
    r = client.put(f"/api/uploads/{uid}?offset=6", content=data[6:])
    assert r.json()["status"] == "complete"

    r = client.post("/api/projects", json={"upload_id": uid, "settings": {"clip_length": "30-60", "language": "cs",
                                                                          "aspect": "1:1", "focus": "peníze"}})
    assert r.status_code == 201, r.text
    p = r.json()
    assert p["name"] == "film" and p["status"] == "queued" and p["settings"]["focus"] == "peníze"
    assert client.enqueued == [("app.jobs.process_project", (p["id"],))]  # type: ignore[attr-defined]
    assert [x["id"] for x in client.get("/api/projects").json()] == [p["id"]]
    r = client.patch(f"/api/projects/{p['id']}", json={"name": "Podcast č. 1 – Řeč"})
    assert r.json()["name"] == "Podcast č. 1 – Řeč"


def test_upload_limits(client: TestClient) -> None:
    register(client, "b@example.cz")
    r = client.post("/api/uploads", json={"filename": "huge.mp4", "size": 6 * 1024**3})
    assert r.status_code == 413 and "příliš velký" in r.json()["detail"]
    r = client.post("/api/uploads", json={"filename": "doc.pdf", "size": 100})
    assert r.status_code == 415


def test_users_are_isolated(client: TestClient) -> None:
    register(client, "owner@example.cz")
    uid = upload(client, b"abcdefgh")
    pid = client.post("/api/projects", json={"upload_id": uid}).json()["id"]
    client.post("/api/auth/logout")
    register(client, "intruder@example.cz")
    assert client.get(f"/api/projects/{pid}").status_code == 404
    assert client.delete(f"/api/projects/{pid}").status_code == 404
    assert client.get(f"/api/uploads/{uid}").status_code == 404
    assert client.get("/api/projects").json() == []
    assert client.post("/api/projects", json={"upload_id": uid}).status_code == 404


def test_project_validation(client: TestClient) -> None:
    register(client, "c@example.cz")
    assert client.post("/api/projects", json={}).status_code == 422
    r = client.post("/api/projects", json={"url": "https://example.com/v", "settings": {"language": "xx"}})
    assert r.status_code == 422
    r = client.post("/api/projects", json={"url": "https://example.com/v", "settings": {"range_start": 10, "range_end": 12}})
    assert r.status_code == 422
    r = client.post("/api/projects", json={"url": "https://example.com/v"})
    assert r.status_code == 201 and r.json()["source_type"] == "url"


def test_presets_endpoint(client: TestClient) -> None:
    register(client, "d@example.cz")
    data = client.get("/api/presets").json()
    assert len(data["presets"]) >= 12 and data["fonts"][0]["url"].startswith("/api/fonts/builtin/")
    r = client.post("/api/presets", json={"name": "Můj styl", "base_id": "neon-glow", "style": {"font_size": 99}})
    assert r.status_code == 201 and r.json()["style"]["font_size"] == 99
    assert client.get("/api/presets").json()["user_presets"][0]["name"] == "Můj styl"
    f = client.get(data["fonts"][0]["url"])
    assert f.status_code == 200 and len(f.content) > 10_000


def test_system_reports_missing_key(client: TestClient) -> None:
    register(client, "e@example.cz")
    s = client.get("/api/system").json()
    assert s["llm_provider"] == "anthropic"
    assert s["llm_status"]["ok"] is False and "ANTHROPIC_API_KEY" in s["llm_status"]["message"]
    assert "anthropic_api_key" not in s and "sk-" not in str(s)
    assert s["cost_per_hour"]["claude-haiku-5-5"]["cs"]["usd"] > 0
