from __future__ import annotations

import asyncio
import hmac
import json
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import parse_qs, urlparse

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select, text

from .config import get_settings
from .database import engine, migrate, session_factory
from .models import ResearchRun, RunArtifact, RunEvent
from .repository import append_event, count_active, count_since, get_run, list_runs, store_artifact
from .security import (
    SESSION_COOKIE,
    _DUMMY_PASSWORD_HASH,
    Identity,
    create_session,
    current_identity,
    login_key,
    login_limiter,
    new_csrf_token,
    require_csrf,
    revoke_session,
    validate_public_url,
    verify_password,
)


PACKAGE_ROOT = Path(__file__).resolve().parent


def _template_context(request: Request) -> dict[str, str]:
    del request
    return {"asset_version": get_settings().release_sha[:12]}


templates = Jinja2Templates(directory=PACKAGE_ROOT / "templates", context_processors=[_template_context])


class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    startup_url: str = Field(min_length=8, max_length=2048)
    description: str = Field(default="", max_length=1500)
    mode: Literal["quick", "standard", "deep"] = "standard"
    focus: Literal["general", "design-partners", "b2b", "community"] = "general"

    @field_validator("startup_url")
    @classmethod
    def public_url(cls, value: str) -> str:
        try:
            return validate_public_url(value)
        except ValueError as error:
            raise ValueError(str(error)) from error

    @field_validator("description")
    @classmethod
    def clean_description(cls, value: str) -> str:
        return value.strip()


def run_payload(run: ResearchRun) -> dict:
    return {
        "id": run.id,
        "startup_url": run.startup_url,
        "mode": run.mode,
        "focus": run.focus,
        "status": run.status,
        "stage": run.stage,
        "model": run.model,
        "workflow_sha": run.workflow_sha,
        "prompt_hash": run.prompt_hash,
        "provider_response_id": run.provider_response_id,
        "error_code": run.error_code,
        "error_message": run.error_message,
        "created_at": run.created_at.isoformat(),
        "updated_at": run.updated_at.isoformat(),
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
    }


@asynccontextmanager
async def lifespan(app: FastAPI):
    del app
    settings = get_settings()
    settings.validate(role="web")
    migrate()
    yield


app = FastAPI(title="Find My Customer", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=PACKAGE_ROOT / "static"), name="static")


@app.middleware("http")
async def security_headers(request: Request, call_next):
    settings = get_settings()
    expected_host = urlparse(settings.public_origin).netloc.lower()
    length_header = request.headers.get("content-length", "0")
    try:
        content_length = int(length_header)
    except ValueError:
        content_length = -1
    if settings.production and request.headers.get("host", "").lower() != expected_host:
        response = JSONResponse({"detail": "Invalid host"}, status_code=status.HTTP_400_BAD_REQUEST)
    elif content_length < 0:
        response = JSONResponse({"detail": "Invalid Content-Length"}, status_code=status.HTTP_400_BAD_REQUEST)
    elif request.method in {"POST", "PUT", "PATCH"} and content_length > 16_384:
        response = JSONResponse({"detail": "Request body too large"}, status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)
    else:
        public = request.url.path in {"/health/live", "/health/ready", "/api/release", "/login"} or request.url.path.startswith("/static/")
        if not public:
            try:
                request.state.identity = current_identity(request)
            except HTTPException as error:
                if settings.auth_mode == "local" and request.method == "GET" and not request.url.path.startswith("/api/"):
                    response = RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
                else:
                    response = JSONResponse({"detail": error.detail}, status_code=error.status_code, headers=error.headers)
            else:
                response = await call_next(request)
        else:
            response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN" if request.url.path.endswith("/report") else "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=()"
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    if request.url.path.endswith("/report"):
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; style-src 'unsafe-inline'; img-src data: https:; "
            "font-src data:; frame-ancestors 'self'; base-uri 'none'; form-action 'none'"
        )
    else:
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
            "connect-src 'self'; frame-src 'self'; object-src 'none'; base-uri 'none'; "
            "form-action 'self'; frame-ancestors 'none'"
        )
    if settings.production:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    if (
        request.url.path in {"/", "/login", "/logout"}
        or request.url.path.startswith("/api/auth")
        or request.url.path.startswith("/api/runs")
        or request.url.path.startswith("/runs/")
    ):
        response.headers["Cache-Control"] = "no-store"
    return response


def _identity(request: Request) -> Identity:
    identity = getattr(request.state, "identity", None)
    if identity is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Identity required")
    return identity


def _owned_run(run_id: str, identity: Identity) -> ResearchRun:
    with session_factory()() as session:
        run = get_run(session, run_id, identity.subject)
        if run is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
        session.expunge(run)
        return run


def _csrf_response(response: Response, csrf: str) -> Response:
    settings = get_settings()
    response.set_cookie(
        "fmc_csrf",
        csrf,
        secure=settings.production,
        httponly=False,
        samesite="strict",
        max_age=8 * 60 * 60,
        path="/",
    )
    return response


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    if get_settings().auth_mode != "local":
        return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)
    csrf = request.cookies.get("fmc_csrf") or new_csrf_token()
    response = templates.TemplateResponse(request=request, name="login.html", context={"csrf": csrf})
    return _csrf_response(response, csrf)


@app.post("/login", response_class=HTMLResponse)
async def login_submit(request: Request):
    settings = get_settings()
    if settings.auth_mode != "local":
        return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)
    try:
        values = parse_qs((await request.body()).decode("utf-8"), keep_blank_values=True)
    except UnicodeDecodeError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid form encoding")
    email = values.get("email", [""])[0].strip().lower()
    password = values.get("password", [""])[0]
    submitted_csrf = values.get("csrf", [""])[0]
    require_csrf(request, submitted_csrf)
    key = login_key(request, email)
    retry_after = login_limiter.blocked(key)
    if retry_after:
        response = HTMLResponse("Too many login attempts. Try again later.", status_code=status.HTTP_429_TOO_MANY_REQUESTS)
        response.headers["Retry-After"] = str(retry_after)
        return response
    candidate_hash = settings.admin_password_hash or _DUMMY_PASSWORD_HASH
    password_valid = verify_password(password, candidate_hash)
    email_valid = bool(settings.admin_email) and hmac.compare_digest(email, settings.admin_email)
    if not (password_valid and email_valid):
        login_limiter.failure(key)
        return HTMLResponse("Invalid email or password.", status_code=status.HTTP_401_UNAUTHORIZED)
    login_limiter.success(key)
    identity = Identity(subject=f"local:{settings.admin_email}", email=settings.admin_email)
    token = create_session(identity)
    response = RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(
        SESSION_COOKIE,
        token,
        secure=settings.production,
        httponly=True,
        samesite="strict",
        max_age=8 * 60 * 60,
        path="/",
    )
    return response


@app.post("/logout")
async def logout(request: Request):
    body = parse_qs((await request.body()).decode("utf-8"), keep_blank_values=True)
    require_csrf(request, body.get("csrf", [""])[0])
    token = request.cookies.get(SESSION_COOKIE, "")
    revoke_session(token)
    response = RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response


@app.get("/health/live", include_in_schema=False)
def health_live() -> dict:
    return {"status": "ok"}


@app.get("/health/ready", include_in_schema=False)
def health_ready() -> dict:
    with engine().connect() as connection:
        connection.execute(text("SELECT 1"))
    return {"status": "ready"}


@app.get("/api/release", include_in_schema=False)
def release_identity() -> dict:
    settings = get_settings()
    model = settings.nvidia_model if settings.provider == "nvidia" else settings.openai_model
    return {"release_sha": settings.release_sha, "provider": settings.provider, "model": model, "schema_version": 1}


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    identity = _identity(request)
    csrf = request.cookies.get("fmc_csrf") or new_csrf_token()
    with session_factory()() as session:
        runs = list_runs(session, identity.subject)
    requested_run_id = request.query_params.get("run", "")
    selected_run = next((run for run in runs if run.id == requested_run_id), None)
    if selected_run is None:
        selected_run = next((run for run in runs if run.status in {"queued", "running"}), None)
    response = templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "identity": identity,
            "runs": runs,
            "selected_run": selected_run,
            "csrf": csrf,
            "release": get_settings().release_sha[:12],
        },
    )
    response.set_cookie(
        "fmc_csrf",
        csrf,
        secure=get_settings().production,
        httponly=False,
        samesite="strict",
        max_age=8 * 60 * 60,
    )
    return response


@app.post("/api/runs", status_code=status.HTTP_201_CREATED)
def create_run(request: Request, payload: RunRequest):
    require_csrf(request)
    identity = _identity(request)
    settings = get_settings()
    now = datetime.now(timezone.utc)
    with session_factory()() as session:
        if count_active(session, identity.subject) >= settings.run_limit_active:
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Active run limit reached")
        if count_since(session, identity.subject, now - timedelta(days=1)) >= settings.run_limit_daily:
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Daily run limit reached")
        run = ResearchRun(
            owner_subject=identity.subject,
            owner_email=identity.email,
            startup_url=payload.startup_url,
            description=payload.description,
            mode=payload.mode,
            focus=payload.focus,
            status="queued",
            stage="queued",
            workflow_sha=settings.release_sha,
            model=settings.nvidia_model if settings.provider == "nvidia" else settings.openai_model,
        )
        session.add(run)
        session.flush()
        append_event(session, run, "queued", "Run queued for evidence research.", event_type="created")
        store_artifact(
            session,
            run.id,
            "input",
            "application/json",
            json.dumps(payload.model_dump(), indent=2, ensure_ascii=False) + "\n",
        )
        session.commit()
        return JSONResponse(run_payload(run), status_code=status.HTTP_201_CREATED)


@app.get("/runs/{run_id}", response_class=HTMLResponse)
def run_detail(request: Request, run_id: str):
    identity = _identity(request)
    with session_factory()() as session:
        run = get_run(session, run_id, identity.subject)
        if run is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
        events = list(session.scalars(select(RunEvent).where(RunEvent.run_id == run.id).order_by(RunEvent.id)))
        artifacts = list(session.scalars(select(RunArtifact).where(RunArtifact.run_id == run.id).order_by(RunArtifact.created_at)))
        return templates.TemplateResponse(
            request=request,
            name="run.html",
            context={"identity": identity, "run": run, "events": events, "artifacts": artifacts},
        )


@app.get("/api/runs/{run_id}")
def api_run(request: Request, run_id: str):
    return run_payload(_owned_run(run_id, _identity(request)))


@app.get("/api/runs/{run_id}/result")
def api_run_result(request: Request, run_id: str):
    artifact = _artifact(run_id, "report-json", _identity(request))
    try:
        report = json.loads(artifact.body)
    except json.JSONDecodeError as error:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Result artifact is invalid") from error
    if not isinstance(report, dict):
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Result artifact is invalid")
    return JSONResponse(
        report,
        headers={"Cache-Control": "no-store", "X-Artifact-SHA256": artifact.sha256},
    )


@app.get("/api/runs/{run_id}/events")
async def run_events(request: Request, run_id: str):
    identity = _identity(request)
    _owned_run(run_id, identity)
    try:
        cursor = max(0, int(request.headers.get("Last-Event-ID", request.query_params.get("after", "0"))))
    except ValueError:
        cursor = 0

    async def stream():
        nonlocal cursor
        idle = 0
        while True:
            if await request.is_disconnected():
                return
            with session_factory()() as session:
                run = get_run(session, run_id, identity.subject)
                if run is None:
                    return
                events = list(
                    session.scalars(
                        select(RunEvent).where(RunEvent.run_id == run_id, RunEvent.id > cursor).order_by(RunEvent.id)
                    )
                )
                for event in events:
                    cursor = event.id
                    try:
                        payload = json.loads(event.payload_json)
                    except json.JSONDecodeError:
                        payload = {}
                    if not isinstance(payload, dict):
                        payload = {}
                    data = json.dumps(
                        {
                            "schema_version": 1,
                            "id": event.id,
                            "type": event.event_type,
                            "stage": event.stage,
                            "message": event.message,
                            "created_at": event.created_at.isoformat(),
                            "payload": payload,
                        },
                        separators=(",", ":"),
                    )
                    yield f"id: {event.id}\nevent: run\ndata: {data}\n\n"
                    idle = 0
                if run.status in {"completed", "failed", "cancelled"} and not events:
                    yield f"event: end\ndata: {json.dumps({'status': run.status})}\n\n"
                    return
            idle += 1
            if idle % 10 == 0:
                yield ": keepalive\n\n"
            await asyncio.sleep(1)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )


def _artifact(run_id: str, kind: str, identity: Identity) -> RunArtifact:
    with session_factory()() as session:
        run = get_run(session, run_id, identity.subject)
        if run is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
        artifact = session.scalar(select(RunArtifact).where(RunArtifact.run_id == run.id, RunArtifact.kind == kind))
        if artifact is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Artifact not ready")
        session.expunge(artifact)
        return artifact


@app.get("/runs/{run_id}/report", response_class=HTMLResponse)
def report(request: Request, run_id: str):
    artifact = _artifact(run_id, "report-html", _identity(request))
    return HTMLResponse(artifact.body)


@app.get("/runs/{run_id}/artifacts/{kind}")
def download_artifact(request: Request, run_id: str, kind: Annotated[str, Field(pattern=r"^[a-z-]{1,50}$")]):
    artifact = _artifact(run_id, kind, _identity(request))
    extension = "html" if artifact.content_type.startswith("text/html") else "json" if "json" in artifact.content_type else "txt"
    return Response(
        artifact.body,
        media_type=artifact.content_type,
        headers={
            "Content-Disposition": f'attachment; filename="{run_id}-{kind}.{extension}"',
            "X-Artifact-SHA256": artifact.sha256,
        },
    )


def main() -> None:
    import uvicorn

    uvicorn.run("find_my_customer.web:app", host="0.0.0.0", port=8000, proxy_headers=False)


if __name__ == "__main__":
    main()
