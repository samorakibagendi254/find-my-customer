from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from find_my_customer import config, database
from find_my_customer.security import validate_public_url


@pytest.fixture()
def portal(tmp_path, monkeypatch):
    monkeypatch.setenv("FMC_ENV", "development")
    monkeypatch.setenv("FMC_AUTH_MODE", "development")
    monkeypatch.setenv("FMC_PROVIDER", "fixture")
    monkeypatch.setenv("FMC_PUBLIC_ORIGIN", "http://testserver")
    monkeypatch.setenv("FMC_RELEASE_SHA", "a" * 40)
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'portal.db'}")
    config.get_settings.cache_clear()
    database.session_factory.cache_clear()
    database.engine.cache_clear()
    from find_my_customer.web import app

    with TestClient(app, headers={"X-Dev-Email": "founder@example.com"}) as client:
        yield client

    database.session_factory.cache_clear()
    database.engine.cache_clear()
    config.get_settings.cache_clear()


def test_public_url_rejects_local_and_private_hosts():
    for url in ["http://localhost", "http://127.0.0.1", "http://10.0.0.4", "ftp://example.com"]:
        with pytest.raises(ValueError):
            validate_public_url(url)
    assert validate_public_url("https://example.com/product") == "https://example.com/product"


def test_fixture_run_reaches_audited_report(portal):
    dashboard = portal.get("/")
    assert dashboard.status_code == 200
    assert "Discovery canvas" in dashboard.text
    assert "Your customer map starts here" in dashboard.text
    csrf = dashboard.cookies["fmc_csrf"]

    created = portal.post(
        "/api/runs",
        headers={"Origin": "http://testserver", "X-CSRF-Token": csrf},
        json={
            "startup_url": "https://example.com",
            "description": "A synthetic test product.",
            "mode": "standard",
            "focus": "general",
        },
    )
    assert created.status_code == 201, created.text
    run_id = created.json()["id"]

    from find_my_customer.worker import process_one

    assert process_one() is True
    finished = portal.get(f"/api/runs/{run_id}")
    assert finished.json()["status"] == "completed"
    assert finished.json()["prompt_hash"]

    report = portal.get(f"/runs/{run_id}/report")
    assert report.status_code == 200
    assert "Qualified prospects" in report.text
    assert "default-src 'none'" in report.headers["content-security-policy"]

    detail = portal.get(f"/runs/{run_id}")
    assert "Immutable artifacts" in detail.text
    assert "sandbox" in detail.text

    result = portal.get(f"/api/runs/{run_id}/result")
    assert result.status_code == 200
    assert result.json()["prospects"][0]["name"] == "Northstar Labs"
    assert len(result.headers["x-artifact-sha256"]) == 64
    assert result.headers["cache-control"] == "no-store"

    selected_dashboard = portal.get(f"/?run={run_id}")
    assert f'data-run-id="{run_id}"' in selected_dashboard.text
    assert "data-run-select" in selected_dashboard.text


def test_mutation_requires_csrf(portal):
    response = portal.post(
        "/api/runs",
        json={"startup_url": "https://example.com", "mode": "quick", "focus": "general"},
    )
    assert response.status_code == 403


def test_release_endpoint_is_machine_verifiable(portal):
    response = portal.get("/api/release")
    assert response.status_code == 200
    assert response.json()["release_sha"] == "a" * 40
    assert response.json()["schema_version"] == 1


def test_static_assets_are_versioned_by_release(portal):
    response = portal.get("/")
    assert response.status_code == 200
    assert "/static/portal.css?v=aaaaaaaaaaaa" in response.text
    assert "/static/portal.js?v=aaaaaaaaaaaa" in response.text


def test_dashboard_javascript_keeps_new_mission_on_canvas():
    script = (Path(__file__).parents[1] / "src" / "find_my_customer" / "static" / "portal.js").read_text(
        encoding="utf-8"
    )
    assert "await canvas?.activateRun(payload.id)" in script
    assert "window.location.assign(`/runs/" not in script
    assert "/result`" in script


def test_source_ledger_must_cover_every_evidence_url():
    from find_my_customer.worker import _verify_source_ledger

    report = {"prospects": [{"sources": [{"url": "https://example.com/evidence"}]}]}
    _verify_source_ledger(report, [{"url": "https://example.com/evidence", "title": "Evidence"}])
    with pytest.raises(RuntimeError, match="missing 1"):
        _verify_source_ledger(report, [])
