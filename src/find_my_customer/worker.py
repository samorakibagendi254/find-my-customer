from __future__ import annotations

import json
import logging
import os
import socket
import time
import traceback

from .config import get_settings
from .database import migrate, session_factory
from .prompt import build_prompt
from .provider import provider_for
from .repository import artifact_exists, claim_next, fail_run, finish_run, renew_lease, set_stage, store_artifact
from .skill_runtime import audit_and_render


logger = logging.getLogger("find_my_customer.worker")


def _evidence_urls(report: dict) -> set[str]:
    return {
        source["url"]
        for prospect in report.get("prospects", [])
        for source in prospect.get("sources", [])
        if isinstance(source, dict) and isinstance(source.get("url"), str)
    }


def _verify_source_ledger(report: dict, ledger: list[dict[str, str]]) -> None:
    expected = _evidence_urls(report)
    observed = {item.get("url") for item in ledger}
    missing = sorted(expected - observed)
    if missing:
        raise RuntimeError(f"source ledger is missing {len(missing)} evidence URL(s)")


def process_one() -> bool:
    settings = get_settings()
    worker_id = f"{socket.gethostname()}:{os.getpid()}"
    factory = session_factory()
    with factory() as session:
        run = claim_next(session, worker_id)
        if run is None:
            return False
        try:
            if artifact_exists(session, run.id, "report-html"):
                finish_run(session, run)
                return True
            set_stage(session, run, "researching", "Defining the ICP and searching current public signals.")
            prompt = build_prompt(run.startup_url, run.description, run.mode, run.focus)
            run.prompt_hash = prompt.sha256
            if not artifact_exists(session, run.id, "prompt"):
                store_artifact(session, run.id, "prompt", "text/plain; charset=utf-8", prompt.instructions + "\n\n" + prompt.input_text)
            session.commit()

            provider = provider_for(settings)
            def heartbeat(response_id: str | None = None) -> None:
                if response_id:
                    run.provider_response_id = response_id
                renew_lease(session, run, worker_id)

            result = provider.run(
                prompt,
                response_id=run.provider_response_id,
                on_created=heartbeat,
                on_poll=heartbeat,
            )
            run.provider_response_id = result.response_id
            run.usage_json = json.dumps(result.usage, sort_keys=True, separators=(",", ":"))
            if not artifact_exists(session, run.id, "source-ledger"):
                store_artifact(
                    session,
                    run.id,
                    "source-ledger",
                    "application/json",
                    json.dumps(result.source_ledger, indent=2, ensure_ascii=False) + "\n",
                )
            session.commit()

            set_stage(session, run, "qualifying", "Qualifying fit, timing, evidence quality, and reachability.")
            set_stage(session, run, "validating", "Running the deterministic scoring and evidence audit.")
            try:
                normalized, html, warnings = audit_and_render(result.report)
            except Exception as validation_error:
                issues = getattr(validation_error, "issues", None)
                if not issues:
                    raise
                set_stage(session, run, "validating", "The first draft missed the contract; applying one bounded repair.")
                result = provider.repair(
                    result,
                    [str(item) for item in issues],
                    on_created=heartbeat,
                    on_poll=heartbeat,
                )
                run.provider_response_id = result.response_id
                run.usage_json = json.dumps(result.usage, sort_keys=True, separators=(",", ":"))
                normalized, html, warnings = audit_and_render(result.report)
            if settings.provider == "openai":
                _verify_source_ledger(normalized, result.source_ledger)
            if not artifact_exists(session, run.id, "report-json"):
                store_artifact(
                    session,
                    run.id,
                    "report-json",
                    "application/json",
                    json.dumps(normalized, indent=2, ensure_ascii=False) + "\n",
                )
            if not artifact_exists(session, run.id, "validation"):
                store_artifact(
                    session,
                    run.id,
                    "validation",
                    "application/json",
                    json.dumps({"warnings": warnings}, indent=2, ensure_ascii=False) + "\n",
                )
            set_stage(session, run, "rendering", "Rendering the standalone, source-linked report.")
            if not artifact_exists(session, run.id, "report-html"):
                store_artifact(session, run.id, "report-html", "text/html; charset=utf-8", html)
            finish_run(session, run)
            return True
        except Exception as error:  # boundary: never expose provider details to users
            logger.error("run_failed run_id=%s error=%s\n%s", run.id, type(error).__name__, traceback.format_exc())
            session.rollback()
            current = session.get(type(run), run.id)
            if current is not None:
                fail_run(session, current, type(error).__name__, "The research run could not be completed. Review the audit log and retry.")
            return True


def main() -> None:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = get_settings()
    settings.validate(role="worker")
    migrate()
    logger.info("worker_started release=%s provider=%s", settings.release_sha, settings.provider)
    while True:
        worked = process_one()
        if not worked:
            time.sleep(settings.worker_poll_seconds)


if __name__ == "__main__":
    main()
