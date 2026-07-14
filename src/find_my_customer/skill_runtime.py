from __future__ import annotations

import importlib.util
import json
import sys
from functools import lru_cache
from pathlib import Path
from types import ModuleType


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SKILL_ROOT = REPOSITORY_ROOT / "find-first-customers"


def _load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load canonical skill module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@lru_cache(maxsize=1)
def modules() -> tuple[ModuleType, ModuleType]:
    model = _load("report_model", SKILL_ROOT / "scripts" / "report_model.py")
    renderer = _load("fmc_generate_report", SKILL_ROOT / "scripts" / "generate_report.py")
    return model, renderer


def report_schema() -> dict:
    return json.loads((SKILL_ROOT / "references" / "report.schema.json").read_text(encoding="utf-8"))


def audit_and_render(raw_report: dict) -> tuple[dict, str, list[str]]:
    model, renderer = modules()
    result = model.audit_report(raw_report)
    result.raise_for_errors()
    css = (SKILL_ROOT / "assets" / "report.css").read_text(encoding="utf-8")
    html = renderer.build_html(result.data, css)
    warnings = [str(item) for item in result.warnings]
    return result.data, html, warnings
