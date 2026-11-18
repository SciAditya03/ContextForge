"""HTTP API end-to-end: upload → progress → intelligence → documents → search → downloads."""

import io
import json
import time
import zipfile

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():  # type: ignore[no-untyped-def]
    from app.core.config import get_settings
    from app.main import create_app

    get_settings.cache_clear()
    with TestClient(create_app(get_settings())) as c:
        yield c


def wait_done(client: TestClient, pid: str, timeout: float = 60) -> dict:  # type: ignore[type-arg]
    deadline = time.time() + timeout
    while time.time() < deadline:
        p = client.get(f"/api/projects/{pid}").json()
        if p["status"] in ("completed", "failed", "cancelled"):
            return p
        time.sleep(0.2)
    raise AssertionError("analysis did not finish")


def upload(client: TestClient, path, **form) -> dict:  # type: ignore[no-untyped-def,type-arg]
    with open(path, "rb") as fh:
        r = client.post("/api/projects", files={"file": (path.name, fh, "application/zip")}, data=form)
    assert r.status_code == 202, r.text
    return r.json()


def test_health_and_settings_never_expose_keys(client: TestClient):
    assert client.get("/api/health").json()["status"] == "ok"
    s = client.get("/api/settings").json()
    assert s["provider"]["provider"] == "none" and "anthropic" in s["providers"]
    r = client.put("/api/settings/keys/openai", json={"api_key": "sk-test-secret-value-1234567890"})
    assert r.json() == {"provider": "openai", "api_key_set": True, "source": "stored"}
    dump = json.dumps(client.get("/api/settings").json())
    assert "sk-test-secret-value" not in dump and '"api_key_set": true' in dump
    assert client.put("/api/settings/keys/bogus", json={"api_key": "x" * 10}).status_code == 400
    assert client.delete("/api/settings/keys/openai").json()["api_key_set"] is False
    bad = client.put("/api/settings/provider", json={"provider": "nope"})
    assert bad.status_code == 422
    ok = client.put("/api/settings/analysis", json={"depth": "quick", "token_budget": 50000, "exclusions": ["node_modules/", "dist/"]})
    assert ok.json()["analysis"]["depth"] == "quick"


def test_upload_validation(client: TestClient, tmp_path):
    p = tmp_path / "notzip.txt"
    p.write_text("hello")
    with open(p, "rb") as fh:
        assert client.post("/api/projects", files={"file": ("notzip.txt", fh)}).status_code == 400
    fake = tmp_path / "fake.zip"
    fake.write_bytes(b"not really a zip")
    with open(fake, "rb") as fh:
        r = client.post("/api/projects", files={"file": ("fake.zip", fh)})
    assert r.status_code == 400 and "not a ZIP" in r.json()["detail"]


def test_traversal_archive_fails_cleanly(client: TestClient, tmp_path):
    z = tmp_path / "evil.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("../../escape.txt", "x")
    pid = upload(client, z)["id"]
    p = wait_done(client, pid)
    assert p["status"] == "failed" and "Unsafe path" in p["error"]
    stages = {s["key"]: s["status"] for s in p["stages"]}
    assert stages["extracting"] == "failed"


def test_full_deterministic_workflow(client: TestClient, sample_zip):
    pid = upload(client, sample_zip("fullstack-notes"), name="Notes", description="demo", depth="standard")["id"]
    p = wait_done(client, pid)
    assert p["status"] == "completed", p.get("error")
    stages = {s["key"]: s["status"] for s in p["stages"]}
    assert stages["parsing"] == "done" and stages["architecture"] == "skipped" and stages["complete"] == "done"
    # progress stream replays real stage events and terminates
    with client.stream("GET", f"/api/projects/{pid}/events") as r:
        body = "".join(r.iter_text())
    assert "event: stage" in body and '"status": "completed"' in body

    intel = client.get(f"/api/projects/{pid}/intelligence").json()
    assert intel["overview"]["included_files"] > 10 and intel["routes"] and intel["db_models"]
    assert {t["name"] for t in intel["technologies"]} >= {"Express", "Prisma", "PostgreSQL", "React"}
    assert intel["output_validation"]["ok"] is True

    docs = client.get(f"/api/projects/{pid}/documents").json()
    paths = {d["path"] for d in docs}
    assert "CONTEXTFORGE_PROJECT_CONTEXT.md" in paths and "07_API_REFERENCE.md" in paths and "data/ANALYSIS_MANIFEST.json" in paths
    assert len([d for d in docs if d["group"] == "modular"]) == 20
    master = client.get(f"/api/projects/{pid}/documents/CONTEXTFORGE_PROJECT_CONTEXT.md").text
    for i in range(1, 33):
        assert f"\n## {i}. " in master
    assert "`backend/src/routes/notes.ts:" in master and "DETECTED" in master
    assert client.get(f"/api/projects/{pid}/documents/../../../etc/passwd").status_code == 404
    assert client.get(f"/api/projects/{pid}/documents/%2e%2e/upload.zip").status_code == 404

    hits = client.get(f"/api/projects/{pid}/search", params={"q": "requireAuth"}).json()
    assert hits["results"] and all("requireauth" in h["snippet"].lower() for h in hits["results"])

    for view in ("modules", "files", "api", "database"):
        g = client.get(f"/api/projects/{pid}/graph", params={"view": view}).json()
        assert g["nodes"], view
    files = client.get(f"/api/projects/{pid}/files").json()
    assert any(f["analysis"] == "deterministic_only" for f in files)

    m = client.get(f"/api/projects/{pid}/download/master")
    assert m.status_code == 200 and m.text.startswith("# Notes — Project Context")
    pkg = client.get(f"/api/projects/{pid}/download/package")
    zf = zipfile.ZipFile(io.BytesIO(pkg.content))
    names = zf.namelist()
    assert "contextforge-Notes/CONTEXTFORGE_PROJECT_CONTEXT.md" in names and "contextforge-Notes/layers/BUG_ANALYSIS.md" in names
    assert "contextforge-Notes/data/DEPENDENCY_GRAPH.json" in names
    assert client.post(f"/api/projects/{pid}/cancel").status_code == 409
    assert client.delete(f"/api/projects/{pid}").json() == {"deleted": pid}
    assert client.get(f"/api/projects/{pid}").status_code == 404


def test_full_workflow_with_llm_provider(client: TestClient, sample_zip, fake_openai_server):
    """Same flow with a configured (fake) OpenAI-compatible LLM endpoint: real HTTP calls, all AI stages."""
    r = client.put("/api/settings/provider", json={"provider": "openai_compatible", "model": "local-model", "base_url": fake_openai_server["base_url"]})
    assert r.status_code == 200
    t = client.post("/api/settings/test", json={}).json()
    assert t["ok"] is True, t
    assert client.post("/api/settings/models", json={}).json()["models"] == ["fake-model-a", "fake-model-b"]
    before = len(fake_openai_server["state"]["requests"])
    pid = upload(client, sample_zip("python-fastapi-shop"), depth="quick")["id"]
    p = wait_done(client, pid)
    assert p["status"] == "completed", p.get("error")
    assert len(fake_openai_server["state"]["requests"]) - before >= 5  # B, C, D, E1, E2
    intel = client.get(f"/api/projects/{pid}/intelligence").json()
    assert intel["ai"]["enabled"] and intel["ai"]["stages"]["E"] == "ok"
    assert intel["synthesis"]["purpose"] and intel["module_summaries"]
    master = client.get(f"/api/projects/{pid}/documents/CONTEXTFORGE_PROJECT_CONTEXT.md").text
    assert "AI_INTERPRETED" in master and "openai_compatible/local-model" in master
    sent = json.dumps(fake_openai_server["state"]["requests"][before:])
    assert "a8F3kL9qZ2xV7mN4pR6tY1wE5uI0oPq" not in sent  # fake secret in the sample never reaches the provider
    assert "a8F3kL9qZ2xV7mN4pR6tY1wE5uI0oPq" not in master


def test_cancel_running_analysis(client: TestClient, sample_zip, monkeypatch):
    import asyncio

    from app.services.pipeline import runner

    orig = runner.scan_repository

    def slow_scan(*a, **k):  # type: ignore[no-untyped-def]
        import time as _t

        _t.sleep(1.0)
        return orig(*a, **k)

    monkeypatch.setattr(runner, "scan_repository", slow_scan)
    pid = upload(client, sample_zip("nextjs-ts-dashboard"))["id"]
    time.sleep(0.3)
    assert client.post(f"/api/projects/{pid}/cancel").json()["cancelled"] is True
    p = wait_done(client, pid)
    assert p["status"] == "cancelled"
    _ = asyncio


def test_api_token_gate(monkeypatch):
    monkeypatch.setenv("CONTEXTFORGE_API_TOKEN", "s3cret-token")
    from app.core.config import get_settings
    from app.main import create_app

    get_settings.cache_clear()
    with TestClient(create_app(get_settings())) as c:
        assert c.get("/api/health").status_code == 200
        assert c.get("/api/projects").status_code == 401
        assert c.get("/api/projects", headers={"Authorization": "Bearer s3cret-token"}).status_code == 200
        assert c.get("/api/projects", params={"token": "s3cret-token"}).status_code == 200


def test_official_provider_base_url_override_is_opt_in(client: TestClient):
    r = client.put("/api/settings/provider", json={"provider": "anthropic", "base_url": "https://attacker.example"})
    assert r.status_code == 400 and "disabled" in r.json()["detail"]
    assert client.post("/api/settings/test", json={"provider": "openai", "base_url": "https://attacker.example"}).status_code == 400
    ok = client.put("/api/settings/provider", json={"provider": "openai_compatible", "base_url": "http://127.0.0.1:1/v1", "model": "m"})
    assert ok.status_code == 200
