from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .models import ResearchRun, RunArtifact, RunEvent


TERMINAL_STATUSES = {"completed", "failed", "cancelled"}


def append_event(
    session: Session,
    run: ResearchRun,
    stage: str,
    message: str,
    *,
    event_type: str = "stage",
    payload: dict | None = None,
) -> RunEvent:
    run.stage = stage
    run.updated_at = datetime.now(timezone.utc)
    event = RunEvent(
        run_id=run.id,
        event_type=event_type,
        stage=stage,
        message=message,
        payload_json=json.dumps(payload or {}, sort_keys=True, separators=(",", ":")),
    )
    session.add(event)
    return event


def store_artifact(session: Session, run_id: str, kind: str, content_type: str, body: str) -> RunArtifact:
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    artifact = RunArtifact(
        run_id=run_id,
        kind=kind,
        content_type=content_type,
        body=body,
        sha256=digest,
        size_bytes=len(body.encode("utf-8")),
    )
    session.add(artifact)
    return artifact


def artifact_exists(session: Session, run_id: str, kind: str) -> bool:
    return session.scalar(
        select(RunArtifact.id).where(RunArtifact.run_id == run_id, RunArtifact.kind == kind).limit(1)
    ) is not None


def get_run(session: Session, run_id: str, owner_subject: str | None = None) -> ResearchRun | None:
    query = select(ResearchRun).where(ResearchRun.id == run_id)
    if owner_subject is not None:
        query = query.where(ResearchRun.owner_subject == owner_subject)
    return session.scalar(query)


def list_runs(session: Session, owner_subject: str, limit: int = 30) -> list[ResearchRun]:
    return list(
        session.scalars(
            select(ResearchRun)
            .where(ResearchRun.owner_subject == owner_subject)
            .order_by(ResearchRun.created_at.desc())
            .limit(limit)
        )
    )


def count_active(session: Session, owner_subject: str) -> int:
    return int(
        session.scalar(
            select(func.count()).select_from(ResearchRun).where(
                ResearchRun.owner_subject == owner_subject,
                ResearchRun.status.in_(["queued", "running"]),
            )
        )
        or 0
    )


def count_since(session: Session, owner_subject: str, since: datetime) -> int:
    return int(
        session.scalar(
            select(func.count()).select_from(ResearchRun).where(
                ResearchRun.owner_subject == owner_subject,
                ResearchRun.created_at >= since,
            )
        )
        or 0
    )


def claim_next(session: Session, worker_id: str, lease_seconds: int = 90) -> ResearchRun | None:
    now = datetime.now(timezone.utc)
    query = (
        select(ResearchRun)
        .where(
            ResearchRun.status.in_(["queued", "running"]),
            or_(ResearchRun.lease_until.is_(None), ResearchRun.lease_until < now),
        )
        .order_by(ResearchRun.created_at)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    run = session.scalar(query)
    if run is None:
        return None
    run.status = "running"
    run.lease_owner = worker_id
    run.lease_until = now + timedelta(seconds=lease_seconds)
    append_event(session, run, run.stage, "Worker accepted the run.", event_type="worker")
    session.commit()
    return run


def renew_lease(session: Session, run: ResearchRun, worker_id: str, lease_seconds: int = 90) -> None:
    if run.status != "running" or run.lease_owner != worker_id:
        raise RuntimeError("worker no longer owns this run lease")
    run.lease_until = datetime.now(timezone.utc) + timedelta(seconds=lease_seconds)
    session.commit()


def set_stage(session: Session, run: ResearchRun, stage: str, message: str) -> None:
    append_event(session, run, stage, message)
    session.commit()


def finish_run(session: Session, run: ResearchRun) -> None:
    run.status = "completed"
    run.completed_at = datetime.now(timezone.utc)
    run.lease_owner = None
    run.lease_until = None
    append_event(session, run, "completed", "Report is ready.", event_type="completed")
    session.commit()


def fail_run(session: Session, run: ResearchRun, code: str, safe_message: str) -> None:
    run.status = "failed"
    run.error_code = code[:80]
    run.error_message = safe_message[:500]
    run.completed_at = datetime.now(timezone.utc)
    run.lease_owner = None
    run.lease_until = None
    append_event(session, run, "failed", safe_message, event_type="failed", payload={"code": code})
    session.commit()
