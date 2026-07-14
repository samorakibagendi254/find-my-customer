from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "find-first-customers"
SCRIPTS = SKILL / "scripts"
FIXTURE = ROOT / "examples" / "analysis.example.json"
sys.path.insert(0, str(SCRIPTS))

from generate_report import STYLESHEET, build_html, safe_url  # noqa: E402
from report_model import audit_report  # noqa: E402


class GenerateReportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = json.loads(FIXTURE.read_text(encoding="utf-8"))
        cls.data = audit_report(cls.source).data
        cls.css = STYLESHEET.read_text(encoding="utf-8")

    def test_report_contains_audit_sections_and_sources(self):
        output = build_html(self.data, self.css)
        self.assertIn("Observed", output)
        self.assertIn("Inferred", output)
        self.assertIn("Score breakdown", output)
        self.assertIn("Original evidence", output)
        self.assertIn("Northstar Labs", output)
        self.assertEqual(3, output.count('class="prospect card"'))

    def test_untrusted_text_is_escaped(self):
        data = copy.deepcopy(self.data)
        data["title"] = "<script>alert(1)</script>"
        data["prospects"][0]["name"] = '<img src=x onerror="alert(1)">'
        output = build_html(data, self.css)
        self.assertNotIn("<script>alert(1)</script>", output)
        self.assertNotIn('<img src=x onerror="alert(1)">', output)
        self.assertIn("&lt;script&gt;", output)

    def test_unsafe_links_are_not_allowed(self):
        self.assertIsNone(safe_url("javascript:alert(1)"))
        self.assertIsNone(safe_url("data:text/html,bad"))
        self.assertEqual("https://example.com/path", safe_url("https://example.com/path"))

    def test_cli_generates_standalone_html(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "report.html"
            completed = subprocess.run(
                [sys.executable, str(SCRIPTS / "generate_report.py"), str(FIXTURE), str(output)],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(0, completed.returncode, completed.stderr)
            html = output.read_text(encoding="utf-8")
            self.assertTrue(html.startswith("<!doctype html>"))
            self.assertIn("SignalDesk", html)
            self.assertIn("Print-ready", html)
            self.assertNotIn("onclick=", html)


if __name__ == "__main__":
    unittest.main()
