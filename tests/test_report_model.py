from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "find-first-customers" / "scripts"
FIXTURE = ROOT / "examples" / "analysis.example.json"
SCHEMA = ROOT / "find-first-customers" / "references" / "report.schema.json"
sys.path.insert(0, str(SCRIPTS))

from report_model import audit_report, calculate_score  # noqa: E402


def fixture_data():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


class ReportModelTests(unittest.TestCase):
    def test_fixture_is_valid_and_sorted_by_computed_score(self):
        result = audit_report(fixture_data())
        self.assertEqual([], result.errors)
        self.assertEqual([90, 77, 65], [item["score"] for item in result.data["prospects"]])
        self.assertEqual(
            ["northstar-labs", "orbitstack", "harborcloud"],
            [item["id"] for item in result.data["prospects"]],
        )

    def test_score_formula_is_deterministic(self):
        self.assertEqual(
            90,
            calculate_score(
                {
                    "pain_strength": 5,
                    "product_fit": 5,
                    "timing": 4,
                    "reachability": 4,
                    "evidence_quality": 4,
                }
            ),
        )

    def test_mismatched_supplied_score_is_rejected(self):
        data = fixture_data()
        data["prospects"][0]["score"] = 82
        result = audit_report(data)
        self.assertTrue(any(issue.path.endswith(".score") for issue in result.errors))
        self.assertEqual(90, result.data["prospects"][0]["score"])

    def test_unknown_fields_are_rejected(self):
        data = fixture_data()
        data["prospects"][0]["private_email"] = "not-allowed@example.com"
        result = audit_report(data)
        self.assertTrue(any("unexpected field" in issue.message for issue in result.errors))

    def test_required_nullable_fields_cannot_be_omitted(self):
        data = fixture_data()
        del data["prospects"][0]["sources"][0]["published_at"]
        result = audit_report(data)
        self.assertTrue(
            any(
                issue.path.endswith(".published_at") and "required field" in issue.message
                for issue in result.errors
            )
        )

    def test_non_public_url_scheme_is_rejected(self):
        data = fixture_data()
        data["prospects"][0]["sources"][0]["url"] = "javascript:alert(1)"
        result = audit_report(data)
        self.assertTrue(any("HTTP or HTTPS" in issue.message for issue in result.errors))

    def test_stale_evidence_emits_warning(self):
        data = fixture_data()
        data["prospects"][0]["sources"][0]["published_at"] = "2024-01-01"
        result = audit_report(data)
        self.assertEqual([], result.errors)
        self.assertTrue(any("older than 365 days" in issue.message for issue in result.warnings))

    def test_none_found_route_requires_null_url_and_warns(self):
        data = fixture_data()
        contact = data["prospects"][0]["contact"]
        contact["route_type"] = "none-found"
        contact["route_url"] = None
        result = audit_report(data)
        self.assertEqual([], result.errors)
        self.assertTrue(any("no direct public contact route" in issue.message for issue in result.warnings))

    def test_mode_limit_is_enforced(self):
        data = fixture_data()
        data["mode"] = "quick"
        for index in range(3):
            extra = copy.deepcopy(data["prospects"][0])
            extra["id"] = f"extra-{index}"
            extra["name"] = f"Extra {index}"
            extra["sources"][0]["url"] = f"https://example.com/extra-{index}"
            data["prospects"].append(extra)
        result = audit_report(data)
        self.assertTrue(any("allows at most 5" in issue.message for issue in result.errors))

    def test_depth_and_focus_are_independent(self):
        data = fixture_data()
        data["mode"] = "quick"
        data["focus"] = "design-partners"
        result = audit_report(data)
        self.assertEqual([], result.errors)

    def test_schema_is_valid_json_with_expected_contract(self):
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        self.assertEqual("object", schema["type"])
        self.assertIn("prospects", schema["required"])
        self.assertFalse(schema["additionalProperties"])


if __name__ == "__main__":
    unittest.main()
