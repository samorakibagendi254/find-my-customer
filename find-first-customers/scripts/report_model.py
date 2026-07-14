#!/usr/bin/env python3
"""Validation and normalization for Find First Customers report data."""

from __future__ import annotations

import copy
import json
import math
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse


DIMENSION_WEIGHTS = {
    "pain_strength": 25,
    "product_fit": 25,
    "timing": 20,
    "reachability": 15,
    "evidence_quality": 15,
}

MODE_LIMITS = {
    "quick": 5,
    "standard": 10,
    "deep": 20,
}

FOCUSES = {"general", "design-partners", "b2b", "community"}

STAGES = {"high-intent", "problem-aware", "trigger-present"}
CONFIDENCE_LEVELS = {"high", "medium", "low"}
CONTACT_ROUTES = {
    "public-thread",
    "official-form",
    "public-business-email",
    "professional-profile",
    "company-page",
    "none-found",
}

_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{1,63}$")


@dataclass(frozen=True)
class Issue:
    severity: str
    path: str
    message: str

    def __str__(self) -> str:
        return f"{self.severity.upper()} {self.path}: {self.message}"


@dataclass
class AuditResult:
    data: dict[str, Any]
    issues: list[Issue]

    @property
    def errors(self) -> list[Issue]:
        return [issue for issue in self.issues if issue.severity == "error"]

    @property
    def warnings(self) -> list[Issue]:
        return [issue for issue in self.issues if issue.severity == "warning"]

    def raise_for_errors(self) -> None:
        if self.errors:
            raise ReportValidationError(self.errors)


class ReportValidationError(ValueError):
    """Raised when report data violates the auditable contract."""

    def __init__(self, issues: Iterable[Issue]):
        self.issues = list(issues)
        message = "Report validation failed:\n" + "\n".join(
            f"- {issue.path}: {issue.message}" for issue in self.issues
        )
        super().__init__(message)


class Auditor:
    def __init__(self, data: Any):
        self.data = copy.deepcopy(data)
        self.issues: list[Issue] = []

    def error(self, path: str, message: str) -> None:
        self.issues.append(Issue("error", path, message))

    def warning(self, path: str, message: str) -> None:
        self.issues.append(Issue("warning", path, message))

    def reject_unknown(self, value: Any, path: str, allowed: set[str]) -> None:
        if not isinstance(value, dict):
            return
        for key in sorted(set(value) - allowed):
            self.error(f"{path}.{key}", "unexpected field")

    def require_keys(self, value: Any, path: str, required: set[str]) -> None:
        if not isinstance(value, dict):
            return
        for key in sorted(required - set(value)):
            self.error(f"{path}.{key}", "required field is missing")

    def require_dict(self, value: Any, path: str) -> dict[str, Any] | None:
        if not isinstance(value, dict):
            self.error(path, "must be an object")
            return None
        return value

    def require_list(self, value: Any, path: str, *, minimum: int = 0) -> list[Any] | None:
        if not isinstance(value, list):
            self.error(path, "must be an array")
            return None
        if len(value) < minimum:
            self.error(path, f"must contain at least {minimum} item(s)")
        return value

    def require_string(self, value: Any, path: str) -> str | None:
        if not isinstance(value, str) or not value.strip():
            self.error(path, "must be a non-empty string")
            return None
        return value.strip()

    def require_string_list(
        self, value: Any, path: str, *, minimum: int = 0, unique: bool = False
    ) -> list[str] | None:
        values = self.require_list(value, path, minimum=minimum)
        if values is None:
            return None
        cleaned: list[str] = []
        for index, item in enumerate(values):
            text = self.require_string(item, f"{path}[{index}]")
            if text is not None:
                cleaned.append(text)
        if unique and len({item.casefold() for item in cleaned}) != len(cleaned):
            self.error(path, "must not contain duplicates")
        return cleaned

    def require_date(self, value: Any, path: str, *, nullable: bool = False) -> date | None:
        if value is None and nullable:
            return None
        text = self.require_string(value, path)
        if text is None:
            return None
        if not _DATE_PATTERN.fullmatch(text):
            self.error(path, "must use YYYY-MM-DD format")
            return None
        try:
            return date.fromisoformat(text)
        except ValueError:
            self.error(path, "must be a valid calendar date")
            return None

    def require_url(self, value: Any, path: str, *, nullable: bool = False) -> str | None:
        if value is None and nullable:
            return None
        text = self.require_string(value, path)
        if text is None:
            return None
        parsed = urlparse(text)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            self.error(path, "must be an absolute HTTP or HTTPS URL")
            return None
        return text

    def audit(self) -> AuditResult:
        root = self.require_dict(self.data, "$")
        if root is None:
            return AuditResult({}, self.issues)

        allowed = {
            "schema_version",
            "title",
            "generated_at",
            "mode",
            "focus",
            "product",
            "icp",
            "research",
            "verdict",
            "prospects",
            "patterns",
            "outreach_plan",
            "limitations",
        }
        self.reject_unknown(root, "$", allowed)
        for key in allowed:
            if key not in root:
                self.error(f"$.{key}", "required field is missing")

        if root.get("schema_version") != 1:
            self.error("$.schema_version", "must equal 1")
        self.require_string(root.get("title"), "$.title")
        generated_at = self.require_date(root.get("generated_at"), "$.generated_at")

        mode = root.get("mode")
        if mode not in MODE_LIMITS:
            self.error("$.mode", f"must be one of {', '.join(MODE_LIMITS)}")
        if root.get("focus") not in FOCUSES:
            self.error("$.focus", f"must be one of {', '.join(sorted(FOCUSES))}")

        self.audit_product(root.get("product"))
        self.audit_icp(root.get("icp"))
        searched_at = self.audit_research(root.get("research"), generated_at)
        self.audit_verdict(root.get("verdict"))
        prospect_ids = self.audit_prospects(root.get("prospects"), mode, generated_at, searched_at)
        self.audit_patterns(root.get("patterns"), prospect_ids)
        self.audit_plan(root.get("outreach_plan"))
        self.require_string_list(root.get("limitations"), "$.limitations", minimum=1)

        prospects = root.get("prospects")
        if isinstance(prospects, list):
            prospects.sort(
                key=lambda prospect: (
                    -prospect.get("score", 0) if isinstance(prospect, dict) else 0,
                    str(prospect.get("name", "")).casefold() if isinstance(prospect, dict) else "",
                )
            )
        return AuditResult(root, self.issues)

    def audit_product(self, value: Any) -> None:
        path = "$.product"
        product = self.require_dict(value, path)
        if product is None:
            return
        fields = {"name", "summary", "url", "outcome", "pricing_motion", "geography"}
        self.reject_unknown(product, path, fields)
        self.require_keys(product, path, {"url"})
        for key in fields - {"url"}:
            self.require_string(product.get(key), f"{path}.{key}")
        self.require_url(product.get("url"), f"{path}.url", nullable=True)

    def audit_profile(self, value: Any, path: str) -> None:
        profile = self.require_dict(value, path)
        if profile is None:
            return
        fields = {"user", "buyer", "job", "trigger", "current_alternative"}
        self.reject_unknown(profile, path, fields)
        for key in fields:
            self.require_string(profile.get(key), f"{path}.{key}")

    def audit_icp(self, value: Any) -> None:
        path = "$.icp"
        icp = self.require_dict(value, path)
        if icp is None:
            return
        self.reject_unknown(icp, path, {"primary", "adjacent", "disqualifiers"})
        self.audit_profile(icp.get("primary"), f"{path}.primary")
        self.audit_profile(icp.get("adjacent"), f"{path}.adjacent")
        self.require_string_list(icp.get("disqualifiers"), f"{path}.disqualifiers", minimum=1)

    def audit_research(self, value: Any, generated_at: date | None) -> date | None:
        path = "$.research"
        research = self.require_dict(value, path)
        if research is None:
            return None
        self.reject_unknown(research, path, {"scope", "searched_at", "source_types"})
        self.require_string(research.get("scope"), f"{path}.scope")
        searched_at = self.require_date(research.get("searched_at"), f"{path}.searched_at")
        self.require_string_list(
            research.get("source_types"), f"{path}.source_types", minimum=1, unique=True
        )
        if searched_at and generated_at and searched_at > generated_at:
            self.error(f"{path}.searched_at", "cannot be later than generated_at")
        return searched_at

    def audit_verdict(self, value: Any) -> None:
        path = "$.verdict"
        verdict = self.require_dict(value, path)
        if verdict is None:
            return
        self.reject_unknown(verdict, path, {"summary", "confidence", "rationale"})
        self.require_string(verdict.get("summary"), f"{path}.summary")
        if verdict.get("confidence") not in CONFIDENCE_LEVELS:
            self.error(f"{path}.confidence", "must be high, medium, or low")
        self.require_string_list(verdict.get("rationale"), f"{path}.rationale", minimum=1)

    def audit_prospects(
        self,
        value: Any,
        mode: Any,
        generated_at: date | None,
        searched_at: date | None,
    ) -> set[str]:
        path = "$.prospects"
        prospects = self.require_list(value, path)
        if prospects is None:
            return set()
        if mode in MODE_LIMITS and len(prospects) > MODE_LIMITS[mode]:
            self.error(path, f"{mode} mode allows at most {MODE_LIMITS[mode]} prospects")

        ids: set[str] = set()
        names: set[str] = set()
        source_owners: dict[str, str] = {}
        for index, prospect_value in enumerate(prospects):
            prospect_path = f"{path}[{index}]"
            prospect = self.require_dict(prospect_value, prospect_path)
            if prospect is None:
                continue
            self.audit_prospect(
                prospect,
                prospect_path,
                ids,
                names,
                source_owners,
                generated_at,
                searched_at,
            )
        return ids

    def audit_prospect(
        self,
        prospect: dict[str, Any],
        path: str,
        ids: set[str],
        names: set[str],
        source_owners: dict[str, str],
        generated_at: date | None,
        searched_at: date | None,
    ) -> None:
        fields = {
            "id",
            "name",
            "type",
            "stage",
            "pain_signal",
            "why_fit",
            "why_now",
            "evidence",
            "sources",
            "dimensions",
            "score",
            "contact",
            "outreach",
            "caution",
        }
        self.reject_unknown(prospect, path, fields)

        prospect_id = self.require_string(prospect.get("id"), f"{path}.id")
        if prospect_id:
            if not _ID_PATTERN.fullmatch(prospect_id):
                self.error(f"{path}.id", "must be a lowercase hyphenated identifier")
            elif prospect_id in ids:
                self.error(f"{path}.id", "duplicate prospect id")
            else:
                ids.add(prospect_id)

        name = self.require_string(prospect.get("name"), f"{path}.name")
        if name:
            folded = name.casefold()
            if folded in names:
                self.warning(f"{path}.name", "duplicate displayed prospect name")
            names.add(folded)

        for key in ("type", "pain_signal", "why_fit", "why_now", "caution"):
            self.require_string(prospect.get(key), f"{path}.{key}")
        if prospect.get("stage") not in STAGES:
            self.error(f"{path}.stage", f"must be one of {', '.join(sorted(STAGES))}")

        self.audit_evidence(prospect.get("evidence"), f"{path}.evidence")
        self.audit_sources(
            prospect.get("sources"),
            f"{path}.sources",
            prospect_id or path,
            source_owners,
            generated_at,
            searched_at,
        )
        computed_score = self.audit_dimensions(prospect.get("dimensions"), f"{path}.dimensions")
        supplied_score = prospect.get("score")
        if supplied_score is not None and supplied_score != computed_score:
            self.error(
                f"{path}.score",
                f"must match the computed score {computed_score}; omit it to normalize automatically",
            )
        prospect["score"] = computed_score
        if computed_score < 50:
            self.error(f"{path}.score", "primary prospects must score at least 50")

        self.audit_contact(prospect.get("contact"), f"{path}.contact")
        self.audit_outreach(prospect.get("outreach"), f"{path}.outreach")

    def audit_evidence(self, value: Any, path: str) -> None:
        evidence = self.require_dict(value, path)
        if evidence is None:
            return
        self.reject_unknown(evidence, path, {"observed", "inferred"})
        self.require_string_list(evidence.get("observed"), f"{path}.observed", minimum=1)
        self.require_string_list(evidence.get("inferred"), f"{path}.inferred")

    def audit_sources(
        self,
        value: Any,
        path: str,
        owner: str,
        source_owners: dict[str, str],
        generated_at: date | None,
        searched_at: date | None,
    ) -> None:
        sources = self.require_list(value, path, minimum=1)
        if sources is None:
            return
        local_urls: set[str] = set()
        for index, source_value in enumerate(sources):
            source_path = f"{path}[{index}]"
            source = self.require_dict(source_value, source_path)
            if source is None:
                continue
            fields = {"title", "url", "type", "published_at", "checked_at", "evidence"}
            self.reject_unknown(source, source_path, fields)
            self.require_keys(source, source_path, {"published_at"})
            for key in ("title", "type", "evidence"):
                self.require_string(source.get(key), f"{source_path}.{key}")
            url = self.require_url(source.get("url"), f"{source_path}.url")
            if url:
                normalized_url = url.rstrip("/").casefold()
                if normalized_url in local_urls:
                    self.error(f"{source_path}.url", "duplicate source within this prospect")
                local_urls.add(normalized_url)
                previous_owner = source_owners.get(normalized_url)
                if previous_owner and previous_owner != owner:
                    self.warning(
                        f"{source_path}.url",
                        f"source is also used by prospect {previous_owner}; verify distinct evidence",
                    )
                source_owners[normalized_url] = owner

            published = self.require_date(
                source.get("published_at"), f"{source_path}.published_at", nullable=True
            )
            checked = self.require_date(source.get("checked_at"), f"{source_path}.checked_at")
            if published is None and source.get("published_at") is None:
                self.warning(f"{source_path}.published_at", "publication date is unavailable")
            if published and checked and published > checked:
                self.error(f"{source_path}.published_at", "cannot be later than checked_at")
            if checked and generated_at and checked > generated_at:
                self.error(f"{source_path}.checked_at", "cannot be later than generated_at")
            freshness_anchor = searched_at or generated_at
            if published and freshness_anchor and (freshness_anchor - published).days > 365:
                self.warning(
                    f"{source_path}.published_at",
                    "signal is older than 365 days; reduce timing and confirm it is still relevant",
                )

    def audit_dimensions(self, value: Any, path: str) -> int:
        dimensions = self.require_dict(value, path)
        if dimensions is None:
            return 0
        self.reject_unknown(dimensions, path, set(DIMENSION_WEIGHTS))
        valid: dict[str, int] = {}
        for key in DIMENSION_WEIGHTS:
            score = dimensions.get(key)
            if isinstance(score, bool) or not isinstance(score, int) or not 0 <= score <= 5:
                self.error(f"{path}.{key}", "must be an integer from 0 to 5")
                valid[key] = 0
            else:
                valid[key] = score
        return calculate_score(valid)

    def audit_contact(self, value: Any, path: str) -> None:
        contact = self.require_dict(value, path)
        if contact is None:
            return
        fields = {"route_type", "route_url", "target_role", "rationale"}
        self.reject_unknown(contact, path, fields)
        self.require_keys(contact, path, {"route_url"})
        route_type = contact.get("route_type")
        if route_type not in CONTACT_ROUTES:
            self.error(f"{path}.route_type", f"must be one of {', '.join(sorted(CONTACT_ROUTES))}")
        route_url = self.require_url(contact.get("route_url"), f"{path}.route_url", nullable=True)
        if route_type == "none-found" and route_url is not None:
            self.error(f"{path}.route_url", "must be null when route_type is none-found")
        if route_type in CONTACT_ROUTES - {"none-found"} and route_url is None:
            self.error(f"{path}.route_url", "is required for a discovered public route")
        for key in ("target_role", "rationale"):
            self.require_string(contact.get(key), f"{path}.{key}")
        if route_type == "none-found":
            self.warning(path, "no direct public contact route was found")

    def audit_outreach(self, value: Any, path: str) -> None:
        outreach = self.require_dict(value, path)
        if outreach is None:
            return
        fields = {"offer", "cta", "opener", "likely_objection"}
        self.reject_unknown(outreach, path, fields)
        for key in fields:
            self.require_string(outreach.get(key), f"{path}.{key}")
        opener = outreach.get("opener")
        if isinstance(opener, str) and len(opener.split()) > 90:
            self.error(f"{path}.opener", "must contain at most 90 words")

    def audit_patterns(self, value: Any, prospect_ids: set[str]) -> None:
        path = "$.patterns"
        patterns = self.require_list(value, path)
        if patterns is None:
            return
        for index, pattern_value in enumerate(patterns):
            pattern_path = f"{path}[{index}]"
            pattern = self.require_dict(pattern_value, pattern_path)
            if pattern is None:
                continue
            fields = {"title", "count", "insight", "supporting_prospect_ids"}
            self.reject_unknown(pattern, pattern_path, fields)
            self.require_string(pattern.get("title"), f"{pattern_path}.title")
            self.require_string(pattern.get("insight"), f"{pattern_path}.insight")
            supporting = self.require_string_list(
                pattern.get("supporting_prospect_ids"),
                f"{pattern_path}.supporting_prospect_ids",
                minimum=2,
                unique=True,
            )
            count = pattern.get("count")
            if isinstance(count, bool) or not isinstance(count, int) or count < 2:
                self.error(f"{pattern_path}.count", "must be an integer of at least 2")
            elif supporting is not None and count != len(supporting):
                self.error(
                    f"{pattern_path}.count",
                    "must equal the number of supporting prospect ids",
                )
            if supporting:
                for prospect_id in supporting:
                    if prospect_id not in prospect_ids:
                        self.error(
                            f"{pattern_path}.supporting_prospect_ids",
                            f"references unknown prospect id {prospect_id}",
                        )

    def audit_plan(self, value: Any) -> None:
        path = "$.outreach_plan"
        plan = self.require_dict(value, path)
        if plan is None:
            return
        fields = {"angle", "steps", "success_metric"}
        self.reject_unknown(plan, path, fields)
        self.require_string(plan.get("angle"), f"{path}.angle")
        self.require_string(plan.get("success_metric"), f"{path}.success_metric")
        steps = self.require_list(plan.get("steps"), f"{path}.steps", minimum=1)
        if steps is None:
            return
        if len(steps) > 7:
            self.error(f"{path}.steps", "must contain at most seven steps")
        days: set[int] = set()
        for index, step_value in enumerate(steps):
            step_path = f"{path}.steps[{index}]"
            step = self.require_dict(step_value, step_path)
            if step is None:
                continue
            self.reject_unknown(step, step_path, {"day", "action", "success_signal"})
            day_value = step.get("day")
            if isinstance(day_value, bool) or not isinstance(day_value, int) or not 1 <= day_value <= 7:
                self.error(f"{step_path}.day", "must be an integer from 1 to 7")
            elif day_value in days:
                self.error(f"{step_path}.day", "duplicate plan day")
            else:
                days.add(day_value)
            self.require_string(step.get("action"), f"{step_path}.action")
            self.require_string(step.get("success_signal"), f"{step_path}.success_signal")


def calculate_score(dimensions: dict[str, int]) -> int:
    """Calculate the 0–100 score from validated 0–5 dimensions."""
    total = sum(dimensions.get(key, 0) / 5 * weight for key, weight in DIMENSION_WEIGHTS.items())
    if not math.isfinite(total):
        raise ValueError("score must be finite")
    return round(total)


def audit_report(data: Any) -> AuditResult:
    return Auditor(data).audit()


def load_json(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError as error:
        raise ReportValidationError([Issue("error", "$", f"file not found: {path}")]) from error
    except json.JSONDecodeError as error:
        raise ReportValidationError(
            [Issue("error", f"$ line {error.lineno}, column {error.colno}", error.msg)]
        ) from error


def load_and_audit(path: Path) -> AuditResult:
    result = audit_report(load_json(path))
    result.raise_for_errors()
    return result


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
