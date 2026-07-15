from __future__ import annotations

import pytest
from argon2 import PasswordHasher
from fastapi.testclient import TestClient

from find_my_customer import config, database
from find_my_customer.security import login_limiter, session_identity


@pytest.fixture()
def local_portal(tmp_path, monkeypatch):
    monkeypatch.setenv("FMC_ENV", "development")
    monkeypatch.setenv("FMC_AUTH_MODE", "local")
    monkeypatch.setenv("FMC_ADMIN_EMAIL", "founder@example.com")
    monkeypatch.setenv("FMC_ADMIN_PASSWORD_HASH", PasswordHasher().hash("correct horse battery staple"))
    monkeypatch.setenv("FMC_PROVIDER", "fixture")
    monkeypatch.setenv("FMC_PUBLIC_ORIGIN", "http://testserver")
    monkeypatch.setenv("FMC_RELEASE_SHA", "b" * 40)
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'auth.db'}")
    config.get_settings.cache_clear()
    database.session_factory.cache_clear()
    database.engine.cache_clear()
    login_limiter._failures.clear()
    from find_my_customer.web import app

    with TestClient(app) as client:
        yield client

    login_limiter._failures.clear()
    database.session_factory.cache_clear()
    database.engine.cache_clear()
    config.get_settings.cache_clear()


def csrf(client: TestClient) -> str:
    response = client.get("/login")
    assert response.status_code == 200
    return response.cookies["fmc_csrf"]


def test_local_auth_redirects_and_sets_secure_session(local_portal):
    client = local_portal
    denied = client.get("/", follow_redirects=False)
    assert denied.status_code == 303
    assert denied.headers["location"] == "/login"
    assert client.get("/api/runs/missing").status_code == 401

    token = csrf(client)
    response = client.post(
        "/login",
        data={"csrf": token, "email": "founder@example.com", "password": "correct horse battery staple"},
        headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "fmc_session=" in response.headers["set-cookie"]
    assert "HttpOnly" in response.headers["set-cookie"]
    assert client.get("/").status_code == 200
    assert "founder@example.com" in client.get("/").text


def test_legal_pages_are_public_and_project_specific(local_portal):
    expected = {
        "/terms": "Find My Customer Terms of Use",
        "/privacy": "Find My Customer Privacy Notice",
        "/deletion": "Delete Your Find My Customer Data",
    }
    for path, marker in expected.items():
        response = local_portal.get(path, follow_redirects=False)
        assert response.status_code == 200
        assert marker in response.text
        assert response.headers["content-type"].startswith("text/html")
        assert response.headers["cache-control"] == "no-store"


def test_bad_credentials_are_generic_and_rate_limited(local_portal):
    client = local_portal
    token = csrf(client)
    responses = [
        client.post(
            "/login",
            data={"csrf": token, "email": "wrong@example.com", "password": "wrong password"},
            headers={"Origin": "http://testserver"},
        )
        for _ in range(6)
    ]
    assert all(response.status_code == 401 for response in responses[:5])
    assert responses[0].text == responses[4].text
    assert responses[-1].status_code == 429
    assert responses[-1].headers["retry-after"]


def test_csrf_and_logout_revoke_session(local_portal):
    client = local_portal
    token = csrf(client)
    login = client.post(
        "/login",
        data={"csrf": token, "email": "founder@example.com", "password": "correct horse battery staple"},
        headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )
    assert login.status_code == 303
    session_token = client.cookies["fmc_session"]
    assert session_identity(session_token) is not None
    logout = client.post("/logout", data={"csrf": token}, headers={"Origin": "http://testserver"}, follow_redirects=False)
    assert logout.status_code == 303
    assert session_identity(session_token) is None
    assert client.get("/", follow_redirects=False).status_code == 303

    missing_csrf = client.post("/login", data={"email": "founder@example.com", "password": "wrong"})
    assert missing_csrf.status_code == 403


def test_production_local_auth_requires_credentials(monkeypatch):
    monkeypatch.setenv("FMC_ENV", "production")
    monkeypatch.setenv("FMC_AUTH_MODE", "local")
    monkeypatch.delenv("FMC_ADMIN_EMAIL", raising=False)
    monkeypatch.delenv("FMC_ADMIN_PASSWORD_HASH", raising=False)
    config.get_settings.cache_clear()
    with pytest.raises(RuntimeError, match="local production auth"):
        config.get_settings().validate(role="web")
    config.get_settings.cache_clear()
